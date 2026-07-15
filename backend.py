#=================================================================
# -- Project Chain Steps (Workflow Diagram) --
#=================================================================

#
#       [ 1. Image Upload ]
#                 │
#                 ▼
#       [ 2. image_to_text ] ──(If no ingredients)──► [ END ]
#                 │
#                 ▼ (Ingredients detected)
#       [ 3. rss_recipe_search ]
#                 │
#                 ▼
#     [ 4. filter_search_results ]
#                 │
#                 ▼
#      [ 5. user selects recipe ]
#                 │
#         ┌───────┴───────┐
#         │               │ (Scrape failed / 403 Forbidden)
#         ▼ (Success)     ▼
#    [ 6/A. scrape ]   [ 6/B. generate_final ]
#    [ _recipe_details ] [ _recipe ]
#         │               │
#         └───────┬───────┘
#                 │
#                 ▼
#          [ 7. response ]
#                 │
#                 ▼
#              [ END ]
#

#=================================================================
# -- Imports --
#=================================================================


import os
import feedparser
from langgraph.graph import StateGraph, START, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableLambda
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import (
    InMemoryChatMessageHistory,
    BaseChatMessageHistory,
)

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, TypedDict
from dotenv import load_dotenv

from transformers import pipeline
import base64
import urllib
import requests
from bs4 import BeautifulSoup


#================================================================
# -- Load Environment Variables --
#================================================================


load_dotenv()

# Opcionális ellenőrzés: megnézzük, hogy sikerült-e beolvasni
if not os.getenv("GEMINI_API_KEY"):
    print("Hiba: A GEMINI_API_KEY nem található a .env fájlban vagy a környezeti változók között!")

llm = ChatGoogleGenerativeAI(model="gemini-3.1-flash-lite", temperature=0.7)


#=================================================================
# -- Pydantic --
#=================================================================

class RecipeResponse(BaseModel):
    recipe: str = Field(description="The generated recipe based on the provided ingredients.")
    cooking_time: str = Field(description="Estimated cooking time for the recipe.")
    difficulty_level: str = Field(description="Difficulty level of the recipe: easy, medium, or hard.")
    ingredients_list: List[str] = Field(
        description="A list of ingredients required for the recipe.",
        default_factory=list,
    )
    steps: List[str] = Field(
        description="Step-by-step instructions for preparing the recipe.",
        default_factory=list,
    )


class RecipeOffer(BaseModel):
    title: str = Field(description="The name of the recipe found in the search results.")
    link: Optional[str] = Field(description="The URL link to the original recipe")
    summary: str = Field(description="A 1-2 sentence description of this recipe and why it fits the ingredients.")


class RecipeSuggestions(BaseModel):
    suggestions: List[RecipeOffer] = Field(
        description="A list of 5 highly relevant recipe suggestions extracted from the search results.",
        max_items=5
    )


class ScrapedRecipeDetails(BaseModel):
    title: str = Field(description="The title of the recipe.")
    ingredients: List[str] = Field(
        description="A list of ingredients required for the recipe.",
        default_factory=list,
    )
    steps: List[str] = Field(
        description="Step-by-step instructions for preparing the recipe.",
        default_factory=list,
    )
    link: Optional[str] = Field(description="The URL link to the original recipe")

#=================================================================
# -- Functions --
#=================================================================


def image_to_text(image_source: str, model: ChatGoogleGenerativeAI = llm) -> str:
    """
    Convert an image (local path or web URL) to text using Gemini.
    """
    
    # 1. Ha a megadott útvonal egy létező helyi fájl a gépeden
    if os.path.exists(image_source):
        with open(image_source, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
        
        # Kitaláljuk a kiterjesztést a megfelelő mime típushoz (pl. .webp -> image/webp)
        ext = os.path.splitext(image_source)[1].lower()
        if ext == ".png":
            mime_type = "image/png"
        elif ext in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        elif ext == ".webp":
            mime_type = "image/webp"
        else:
            mime_type = "image/jpeg"  # biztonsági tartalék
            
        # Ezt a formátumot a Gemini azonnal megérti internet nélkül is:
        formatted_url = f"data:{mime_type};base64,{encoded_string}"
    else:
        # Ha nem helyi fájl, akkor feltételezzük, hogy egy internetes URL (pl. http://...)
        formatted_url = image_source

    # 2. Összeállítjuk a promptot a helyes LangChain struktúrával
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a helpful assistant that can analyze images and describe the ingredients present in them."
            ),

            (
                "user",
                [
                    {"image_url": {
                        "url": "{formatted_url}"
                        }
                    },

                    {"type": "text",
                     "text": "Describe the ingredients in the image provided. If there are no ingredients, just say 'No ingredients found'."
                    }
                ]
            )
        ]
    )

    # 3. Összefűzzük az LCEL láncot
    pipeline = prompt | model | StrOutputParser()

    # 4. Futtatjuk a láncot
    response = pipeline.invoke({"formatted_url": formatted_url})

    return response


def rss_recipe_search(ingredients: str) -> list:
    """
    Searches for the ingredients via RSS and returns a clean JSON-like list.
    """

    print(f"RSS search for: '{ingredients}'...")
    
    # 1. Encoding (e.g., "tomato, basil" -> "tomato%20basil%20recipe")
    search_query = f"{ingredients} recipe"
    encoded_query = urllib.parse.quote(search_query)
    time_filter = "30d"  # Example: last 7 days
    
    # Google News RSS search URL (tuned for Hungarian results)
    # You can set hl=en&gl=US if you want English recipe results
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}%20when:{time_filter}&hl=hu&gl=HU&ceid=HU:hu"
    
    # 2. Beolvassuk és elemezzük az RSS XML feedet
    feed = feedparser.parse(rss_url)
    
    # 3. Kigyűjtjük a legelső 5 legrelevánsabb találatot egy szép, tiszta struktúrába
    structured_results = []
    
    for entry in feed.entries[:10]:  # The following data are extracted from the RSS feed entries
        recipe_item = {
            "title": entry.title,
            "link": entry.link,
            "published": getattr(entry, "published", "N/A"),
            "summary": getattr(entry, "summary", "")
        }
        structured_results.append(recipe_item)
        
    return structured_results


def filter_search_results(ingredients: str, raw_search_text: str, model=llm) -> RecipeSuggestions:
    """
    Given raw search results, extract the 5 most relevant recipe suggestions in a structured format.
    """

    print("The model is extracting the most relevant recipe suggestions...")
    
    # Itt is kényszerítjük a strukturált kimenetet, de most az ajánlatok mintájára
    structured_filter_llm = model.with_structured_output(RecipeSuggestions)
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an advanced information extractor for a cooking application. "
            "Your job is to read through messy web search results (or feed data) and extract exactly 5 "
            "of the most relevant and realistic recipe ideas that match the user's ingredients. "
            "Extract their titles, source links, and provide a very brief summary."
        ),
        (
            "user",
            "User's ingredients: {ingredients}\n\n"
            "Raw Search Results:\n{raw_search_text}\n\n"
            "Please extract the 5 best recipe suggestions in the requested structured format."
        )
    ])
    
    pipeline = prompt | structured_filter_llm

    return pipeline.invoke({
        "ingredients": ingredients,
        "raw_search_text": raw_search_text
    })


def scrape_recipe_details(recipe_url: str, model: ChatGoogleGenerativeAI = llm) -> ScrapedRecipeDetails:
    """
    Downloads the given recipe URL, cleans the HTML,
    and then uses Gemini to extract the recipe in a structured format.
    """

    print(f"\nDownloading webpage: {recipe_url}...")
    
    # We provide a User-Agent header to mimic a real browser, so that websites don't block the request as a bot
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(recipe_url, headers=headers, timeout=15)
        response.raise_for_status()
    except Exception as e:
        print(f"Problem occurred while downloading the webpage: {e}")
        # If the page cannot be downloaded, we return a placeholder ScrapedRecipeDetails object indicating the error
        return ScrapedRecipeDetails(title="Problem occurred while downloading the webpage", link=recipe_url)

    # HTML cleaning and parsing
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # Delete unwanted tags that usually contain non-relevant content (scripts, styles, navigation, footers, etc.)
    for element in soup(["script", "style", "nav", "footer", "iframe", "aside"]):
        element.decompose()
        
    # We extract the visible text from the cleaned HTML
    raw_text = soup.get_text(separator="\n")
    # Clean up the text: remove extra whitespace, empty lines, and leading/trailing spaces
    clean_text = "\n".join([line.strip() for line in raw_text.splitlines() if line.strip()])

    # 3. Invoke Gemini to extract structured data
    print("Extracting recipe data from the website text...")
    structured_parser = model.with_structured_output(ScrapedRecipeDetails)
    
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are an expert recipe extractor. Your task is to analyze the provided raw text "
            "scraped from a cooking website and extract the recipe title, ingredients (with measurements if available), "
            "and step-by-step cooking instructions. "
            "Always return the final extracted recipe in English!"
        ),
        (
            "user",
            "Source URL: {url}\n\n"
            "Raw Website Text:\n{web_text}\n\n"
            "Please extract the detailed recipe into the requested schema."
        )
    ])
    
    pipeline = prompt | structured_parser
    
    # A biztonság kedvéért limitáljuk a karakterek számát (pl. 15000 karakter bőven elég egy recepthez), 
    # hogy elkerüljük a túl hosszú kontextusból adódó lassulást vagy extra token költségeket.
    result = pipeline.invoke({
        "url": recipe_url,
        "web_text": clean_text[:15000]
    })
    
    return result


def generate_final_recipe(ingredients: str, chosen_recipe: RecipeOffer, model: ChatGoogleGenerativeAI = llm) -> RecipeResponse:
    """
    Develops the complete recipe step by step based on the user's chosen online recipe concept.
    """

    print(f"Chef is starting to develop the detailed recipe for: {chosen_recipe.title}...")
    structured_output_model = model.with_structured_output(RecipeResponse)
    
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a creative master chef. Your task is to take the original ingredients "
                "and a specific recipe concept chosen by the user from the web, and build a detailed, "
                "step-by-step structured recipe response. Expand on instructions, add estimated measurements, "
                "and ensure it follows the structure perfectly."
            ),
            (
                "user",
                "Original available ingredients: {ingredients}\n"
                "Chosen Web Recipe Concept: {title}\n"
                "Concept Summary: {summary}\n\n"
                "Please generate the complete, detailed recipe in the requested structured format."
            )
        ]
    )

    pipeline = prompt | structured_output_model
    response = pipeline.invoke({
        "ingredients": ingredients,
        "title": chosen_recipe.title,
        "summary": chosen_recipe.summary
    })

    return response


#=================================================================
# -- LangGraph Workflow Setup --
#=================================================================

# state
class RecipeState(TypedDict):
    image_path: str
    detected_ingredients: Optional[str]
    suggestions_data: Optional[RecipeSuggestions]
    chosen_recipe: Optional[RecipeOffer]
    final_recipe: Optional[ScrapedRecipeDetails]

# node 1
def node_analyze_image(state: RecipeState) -> dict:
    image_path = state["image_path"]
    detected_ingredients = image_to_text(image_path)
    return {"detected_ingredients": detected_ingredients}

# node 2
def node_search_recipes(state: RecipeState) -> dict:
    detected_ingredients = state["detected_ingredients"]
    raw_search_text = rss_recipe_search(detected_ingredients)
    suggestions_data = filter_search_results(detected_ingredients, raw_search_text)
    return {"suggestions_data": suggestions_data}

# node 3
def node_user_selection(state: RecipeState) -> dict:
    suggestions = state["suggestions_data"].suggestions
    print("\n" + "="*60)
    print("    PLEASE CHOOSE FROM THE FOLLOWING 5 ONLINE RECIPE OFFERS:")
    print("="*60)
    
    for i, offer in enumerate(suggestions, 1):
        print(f"\n[{i}] 🍳 {offer.title}")
        print(f"    Source: {offer.link if offer.link else 'No link'}")
        print(f"    Description: {offer.summary}")
        
    print("\n" + "="*60)
    
    while True:
        try:
            choice = int(input("\nEnter the number of the chosen recipe (1-5): "))
            if 1 <= choice <= len(suggestions):
                break
            else:
                print(f"Please enter a number between 1 and {len(suggestions)}!")
        except ValueError:
            print("Please enter a valid number!")
            
    chosen = suggestions[choice - 1]
    print(f"\nYou have successfully chosen: {chosen.title} 🚀")
    return {"chosen_recipe": chosen}

# node 4
def node_generate_recipe(state: RecipeState) -> dict:
    final_recipe = None
    chosen_recipe = state["chosen_recipe"]
    detected_ingredients = state["detected_ingredients"]
    
    if chosen_recipe.link and chosen_recipe.link.startswith("http"):
        try:
            scraped_recipe = scrape_recipe_details(chosen_recipe.link)
            if scraped_recipe.title != "Problem occurred while downloading the webpage":
                print("Recipe successfully scraped!")
                return {"final_recipe": scraped_recipe}
            else:
                print("The scraping failed, switching to generative mode...")
            
        except Exception as e:
            print(f"Failed to read the webpage directly ({e}). Switching to generative mode...")
    
    if not final_recipe:
        try:
            generated_recipe = generate_final_recipe(detected_ingredients, chosen_recipe)
            
            final_recipe = ScrapedRecipeDetails(
                title=generated_recipe.recipe,  # A generált név
                ingredients=generated_recipe.ingredients_list,
                steps=generated_recipe.steps,
                link=chosen_recipe.link
            )
            return {"final_recipe": final_recipe}
        
        except Exception as e:
            print(f"Failed to generate the final recipe ({e}).")

    return {"final_recipe": final_recipe}

# conditional routing function
def decide_after_analysis(state: RecipeState) -> str:
    detected_ingredients = state["detected_ingredients"]

    if "No ingredients found" in detected_ingredients:
        print("No ingredients found in the image. The process is stopping.")
        return "end"
    
    else:
        return "rss_recipe_search"

# graph setup
graph = StateGraph(RecipeState)

# node definitions
graph.add_node("node_analyze_image", node_analyze_image)
graph.add_node("node_search_recipes", node_search_recipes)
graph.add_node("node_user_selection", node_user_selection)
graph.add_node("node_generate_recipe", node_generate_recipe)

# edge definitions
graph.add_edge(START, "node_analyze_image")
graph.add_conditional_edges(
    "node_analyze_image",
    decide_after_analysis,
        {
            "rss_recipe_search": "node_search_recipes",
            "end": END
        }
    )
graph.add_edge("node_search_recipes", "node_user_selection")
graph.add_edge("node_user_selection", "node_generate_recipe")
graph.add_edge("node_generate_recipe", END)

app = graph.compile()



#=================================================================
# -- Execution Flow --
#=================================================================


def main():
    # 1. Megadjuk a képünk elérési útját
    image_path = "C:\\Users\\takacspatrik\\Desktop\\Langchain\\LangChain_course_2\\baking-ingredients-photo.webp"
    
    # --- [LÉPÉS 1: img => txt] ---
    print("\n=== 1. LÉPÉS: Kép elemzése a Gemini-vel... ===")
    detected_ingredients = image_to_text(image_path)
    print(f"Észlelt hozzávalók: {detected_ingredients}\n")
    
    if "No ingredients found" in detected_ingredients:
        print("Nem találtam alapanyagokat a képen. A folyamat leáll.")
        return

    # --- [LÉPÉS 2: web => receipts] ---
    print("=== 2. LÉPÉS: Internetes kutatás indítása... ===")
    raw_search = rss_recipe_search(detected_ingredients)

    # --- [LÉPÉS 3: receipts => 5_relevant] ---
    print("=== 3. LÉPÉS: Az 5 legrelevánsabb ötlet kivonatolása... ===")
    suggestions_data = filter_search_results(detected_ingredients, raw_search)
    
    # --- [LÉPÉS 4: ASK USER TO CHOOSE] ---
    print("\n" + "="*60)
    print("   🌐 KÉRLEK VÁLASSZ AZ ALÁBBI 5 ONLINE RECEPT AJÁNLATBÓL:")
    print("="*60)
    
    for i, offer in enumerate(suggestions_data.suggestions, 1):
        print(f"\n[{i}] 🍳 {offer.title}")
        print(f"    🔗 Forrás: {offer.link if offer.link else 'Nincs link'}")
        print(f"    📝 Leírás: {offer.summary}")
        
    print("\n" + "="*60)
    
    # Interaktív bekérés a felhasználótól a terminálban
    while True:
        try:
            choice = int(input("\nÍrd be a választott recept számát (1-5): "))
            if 1 <= choice <= len(suggestions_data.suggestions):
                break
            else:
                print(f"Kérlek 1 és {len(suggestions_data.suggestions)} közötti számot adj meg!")
        except ValueError:
            print("Kérlek érvényes számot írj be!")
            
    # Elmentjük a felhasználó választását
    chosen_recipe_offer = suggestions_data.suggestions[choice - 1]
    print(f"\nSikeresen kiválasztottad: {chosen_recipe_offer.title} 🚀")

    # --- [LÉPÉS 5: Választás alapján kész, strukturált recept] ---
    print("\n=== 5. LÉPÉS: A választott recept részletes kidolgozása... ===")
    
    final_recipe = None
    
    # Ha van linkje az ajánlatnak, megpróbáljuk lekaparni a teljes weboldalt
    if chosen_recipe_offer.link and chosen_recipe_offer.link.startswith("http"):
        try:
            # Lekaparjuk és strukturáljuk a valódi weboldalt
            scraped_recipe = scrape_recipe_details(chosen_recipe_offer.link)
            
            # Ellenőrizzük, hogy sikeres volt-e (pl. talált-e hozzávalókat és lépéseket)
            if scraped_recipe.ingredients and scraped_recipe.steps:
                print("🎯 Recept sikeresen beolvasva és feldolgozva a weboldalról!")
                final_recipe = scraped_recipe
        except Exception as e:
            print(f"⚠️ Nem sikerült a közvetlen weboldal-olvasás ({e}). Átváltás generatív módra...")

    # Fallback: Ha nem volt link, vagy meghiúsult a kaparás, legeneráltatjuk "fejből"
    if not final_recipe:
        print("🍳 Séf üzemmód: Recept generálása az online koncepció alapján...")
        # Ez a te eredeti generate_final_recipe hívásod
        generated_recipe = generate_final_recipe(detected_ingredients, chosen_recipe_offer)
        
        # Átalakítjuk a formátumot, hogy kompatibilis legyen a ScrapedRecipeDetails sémáddal a kiíratásnál
        final_recipe = ScrapedRecipeDetails(
            title=generated_recipe.recipe,
            ingredients=generated_recipe.ingredients_list,
            steps=generated_recipe.steps,
            link=chosen_recipe_offer.link
        )
    
    # Kiíratás (itt már az új final_recipe objektumot használjuk)
    print("\n" + "="*50)
    print("       🎉 A VÉGLEGES MESTERRECEPT 🎉")
    print("="*50)
    print(f"Recept neve: {final_recipe.title}")
    if final_recipe.link:
        print(f"Eredeti forrás: {final_recipe.link}")
    
    print("\nHozzávalók pontos listája:")
    for ing in final_recipe.ingredients:
        print(f"  • {ing}")
        
    print("\nElkészítés lépései:")
    for i, step in enumerate(final_recipe.steps, 1):
        print(f"  {i}. {step}")


if __name__ == "__main__":

    # --- GRAPH GENERATION (Before running) ---
    # try:
    #     print("\n--- Mermaid Graph Text ---")
    #     print(app.get_graph().draw_mermaid())
        
    #     print("\n🖼️ Generating PNG image...")
    #     png_bytes = app.get_graph().draw_mermaid_png()
    #     mentesi_utvonal = "C:\\Users\\takacspatrik\\Desktop\\Langchain\\LangChain_course_2\\graph_3.png"
        
    #     with open(mentesi_utvonal, "wb") as f:
    #         f.write(png_bytes)
    #     print(f"✅ Graph successfully saved to: {mentesi_utvonal}")
        
    # except Exception as e:
    #     print(f"❌ Visualization failed: {e}")
    #     print("Tip: Check your internet connection or run: pip install pyppeteer")
    
    # print("\n" + "="*50 + "\n")

    # 1. Futtatjuk a gráfot és elmentjük a végső State-et egy változóba
    result_state = app.invoke({"image_path": r"C:\Users\takacspatrik\Desktop\Langchain\project_sef_seged\test_2.jpg"})
    
    # 2. Kinyerjük a kész receptet a State-ből
    final_recipe = result_state.get("final_recipe")
    
    # 3. Kiírjuk az eredményt (ahogy a régi main() függvényedben volt)
    if final_recipe:
        print("\n" + "="*50)
        print("       🎉 FINAL RECIPE 🎉")
        print("="*50)
        print(f"Recipe name: {final_recipe.title}")
        if final_recipe.link:
            print(f"Original source: {final_recipe.link}")
        
        print("\nExact list of ingredients:")
        for ing in final_recipe.ingredients:
            print(f"  • {ing}")
            
        print("\nPreparation steps:")
        for i, step in enumerate(final_recipe.steps, 1):
            print(f"  {i}. {step}")