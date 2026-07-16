# chef_assistant
# 🍳 AI Chef Assistant – Intelligens Receptkereső és -Generáló Alkalmazás

Az **AI Chef Assistant** egy modern, **LangGraph** és **Streamlit** alapú asszisztens, amely képes képekről felismerni a hozzávalókat, valós időben keresni az interneten hozzájuk illő recepteket (RSS feed-en keresztül), majd intelligens web-scraping vagy fejlett generatív AI segítségével részletes, strukturált mesterreceptet készíteni.

A projekt mintapéldája annak, hogyan lehet a legújabb **LangChain (LCEL)**, **LangGraph** és **VLM (Vision-Language Model)** technológiákat ötvözni egy letisztult, Dockerizált mikroszolgáltatásban.

---

## 🏗️ Munkafolyamat & Architektúra (Workflow)

Az alkalmazás mögött álló üzleti logikát egy **LangGraph** állapotgép (StateGraph) vezérli, amely biztosítja a rugalmas állapotkezelést, a hibatűrést és a logikai elágazásokat:

```
          [ 1. Kép Feltöltése ]
                    │
                    ▼
          [ 2. image_to_text ] ──(Nincs alapanyag)──► [ END / Figyelmeztetés ]
                    │
                    ▼ (Alapanyagok észlelve)
          [ 3. rss_recipe_search ]
                    │
                    ▼
        [ 4. filter_search_results ]
                    │
                    ▼
        [ 5. Felhasználói Választás ]
                    │
            ┌───────┴───────┐
            │               │ (Sikertelen kaparás / 403 / Cloudflare)
            ▼ (Sikeres)     ▼
       [ 6/A. scrape ]   [ 6/B. generate_final ]
       [ _recipe_details ] [ _recipe ]
            │               │
            └───────┬───────┘
                    │
                    ▼
             [ 7. Megjelenítés ]
                    │
                    ▼
                 [ END ]
```

---

## ✨ Főbb Funkciók és Mérnöki Megoldások

* **Vizuális Alapanyag-felismerés (VLM):** A `gemini-3.1-flash-lite` modell segítségével az alkalmazás képes elemezni a feltöltött képeket, és pontos szöveges listát készíteni a látott élelmiszerekről.
* **Valós Idejű Internetes Keresés (Google News RSS):** Nem statikus adatbázisból dolgozik. A felismert alapanyagok alapján dinamikusan keres releváns, friss recepteket a weben.
* **Intelligens Információ-szűrés (Structured Output):** A nyers keresési találatokból a Gemini LLM a Pydantic (`RecipeSuggestions`) segítségével kigyűjti a leginkább releváns 5 ötletet, összefoglalva, hogy miért illenek a hűtő tartalmához.
* **Robusztus Web Scraping & Fallback ("Séf") Üzemmód:**
    * **Scraping:** Ha a felhasználó kiválaszt egy receptet, a rendszer letölti a céloldalt, BeautifulSoup segítségével megtisztítja a felesleges HTML elemektől (reklámok, scriptek, lábléc), majd az LLM kinyeri belőle a strukturált hozzávalókat és lépéseket.
    * **Fallback:** Ha a céloldal bot-védett (pl. Cloudflare 403), az alkalmazás elegánsan átvált generatív módba, és a kiválasztott koncepció alapján a virtuális Séf fejleszti ki a teljes receptet.
* **Kliensoldali API Kulcs Kezelés:** A felhasználó saját Gemini API kulcsával futtathatja az alkalmazást, így a szerver oldalon nem tárolódnak érzékeny adatok.
* **Docker-ready Deployment:** Az alkalmazás teljesen konténerizált, így bárhol másodpercek alatt elindítható.

---

## 🛠️ Technológiai Stack

* **Frontend:** [Streamlit](https://streamlit.io/) (Interaktív, modern UI session state-tel)
* **AI Framework:** [LangChain](https://www.langchain.com/) & [LangGraph](https://www.langchain.com/langgraph) (LCEL, StateGraph workflow)
* **LLM/VLM:** Google Gemini (`gemini-3.1-flash-lite`) a `langchain-google-genai` integráción keresztül
* **Data Parsing & Scraping:** [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/), `requests`, `feedparser`
* **Data Validation:** [Pydantic v2](https://docs.pydantic.dev/)
* **Konténerizáció:** [Docker](https://www.docker.com/) (Slim Python 3.11 alapú image)

---

## 🚀 Telepítés és Futtatás

### Opció A: Lokális futtatás (Python virtuális környezet)

1.  **Klónozd a repót:**
    ```bash
    git clone <repo_url>
    cd chef_assistant
    ```

2.  **Hozz létre és aktiválj egy virtuális környezetet:**
    ```bash
    python -m venv venv
    # Windows esetén:
    venv\Scripts\activate
    # Linux/MacOS esetén:
    source venv/bin/activate
    ```

3.  **Telepítsd a függőségeket:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Indítsd el a Streamlit alkalmazást:**
    ```bash
    streamlit run frontend.py
    ```

5.  **Nyisd meg a böngésződben:** `http://localhost:8501`

---

### Opció B: Futtatás Docker használatával 🐳

Az alkalmazás Docker-fájlja optimalizált, és beépített egészségellenőrzést (Healthcheck) is tartalmaz.

1.  **Építsd fel a Docker képet:**
    ```bash
    docker build -t chef-assistant .
    ```

2.  **Futtasd a konténert:**
    ```bash
    docker run -p 8501:8501 chef-assistant
    ```

3.  **Nyisd meg a böngésződben:** `http://localhost:8501`

---

## 🔒 Biztonság és API Kulcsok

Az alkalmazás futtatásához egy **Google Gemini API** kulcsra van szükség, amelyet ingyenesen beszerezhetsz a [Google AI Studio](https://aistudio.google.com/) oldalon.

A kulcsot a Streamlit felület **bal oldali sávjában (Sidebar)** kell megadnod. Ez a kulcs közvetlenül a memóriában (Session State) él a futás ideje alatt, és **soha nem kerül mentésre vagy továbbításra semmilyen külső szerverre** a Google hivatalos API végpontjain kívül.

---

## 📁 Projekt Felépítése

```
chef_assistant/
│
├── frontend.py           # Streamlit UI, állapotkezelés és gombok logikája
├── backend.py            # LangGraph workflow, RSS keresés, scraping és LLM hívások
├── requirements.txt      # Szükséges Python könyvtárak listája
├── Dockerfile            # Gyártásra kész Docker konfiguráció (slim Python bázis)
└── README.md             # Projekt dokumentáció (ez a fájl)
