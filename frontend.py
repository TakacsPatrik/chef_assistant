import streamlit as st
import os
from PIL import Image
from langchain_google_genai import ChatGoogleGenerativeAI

# Import backend functions
from backend import (
    image_to_text,
    rss_recipe_search,
    filter_search_results,
    scrape_recipe_details,
    generate_final_recipe,
    ScrapedRecipeDetails
)

# Page Configuration
st.set_page_config(page_title="AI Recipe Generator", page_icon="🍳", layout="centered")

# ==========================================
# 🔑 API KEY MANAGEMENT IN THE SIDEBAR
# ==========================================
st.sidebar.title("⚙️ Settings")
st.sidebar.markdown("This application requires a personal Google Gemini API key to operate.")

# User inputs their API key
user_api_key = st.sidebar.text_input(
    "Google Gemini API Key", 
    type="password", 
    placeholder="AIzaSy...",
    help="Enter your custom Google AI Studio API key. It is never saved on the server."
)

st.sidebar.markdown(
    "[Get a Free Gemini API Key here](https://aistudio.google.com/)"
)

# Initialize the model dynamically with the user's API Key
user_model = None
if user_api_key:
    user_model = ChatGoogleGenerativeAI(
        model="gemini-3.1-flash-lite", 
        temperature=0.7, 
        google_api_key=user_api_key
    )
else:
    st.sidebar.warning("⚠️ Please provide your API Key in the sidebar to proceed!")

# ==========================================
# 🍳 MAIN APPLICATION INTERFACE
# ==========================================
st.title("🍳 AI Recipe Generator")
st.subheader("Upload a photo of your ingredients and get curated, real-world recipe suggestions!")

# Initialize Streamlit Session States
if "detected_ingredients" not in st.session_state:
    st.session_state.detected_ingredients = None
if "suggestions" not in st.session_state:
    st.session_state.suggestions = None
if "final_recipe" not in st.session_state:
    st.session_state.final_recipe = None

# --- STEP 1: Uploading the Image ---
uploaded_file = st.file_uploader("Choose an image...", type=["jpg", "jpeg", "png", "webp"])

if uploaded_file is not None:
    # Display the uploaded image
    image = Image.open(uploaded_file)
    st.image(image, caption="Uploaded Image", use_container_width=True)
    
    # Save temporarily for processing
    temp_image_path = "temp_uploaded_image.webp"
    image.save(temp_image_path, "WEBP")

    # Button is disabled if no API key is provided
    analyze_disabled = user_model is None
    
    if st.button("🔍 Analyze Ingredients", type="primary", disabled=analyze_disabled):
        with st.spinner("Gemini is analyzing your ingredients..."):
            try:
                # 1. Image-to-Text
                detected = image_to_text(temp_image_path, model=user_model)
                st.session_state.detected_ingredients = detected
                
                if "No ingredients found" in detected:
                    st.error("No recognizable cooking ingredients found in the image. Please try another photo!")
                    st.session_state.suggestions = None
                else:
                    # 2. RSS Search & AI filtering
                    raw_search = rss_recipe_search(detected)
                    suggestions_data = filter_search_results(detected, raw_search, model=user_model)
                    st.session_state.suggestions = suggestions_data.suggestions
                    st.session_state.final_recipe = None  # Reset recipe
            except Exception as e:
                st.error(f"An error occurred. Please verify that your API key is correct! Details: {e}")
            finally:
                # Clean up the temp image
                if os.path.exists(temp_image_path):
                    os.remove(temp_image_path)

# --- STEP 2: Display Detected Ingredients & Suggested Recipes ---
if st.session_state.detected_ingredients:
    st.success(f"**Detected Ingredients:** {st.session_state.detected_ingredients}")

if st.session_state.suggestions and user_model is not None:
    st.write("---")
    st.markdown("### 🌐 Choose one of these 5 recipe concepts:")
    
    # Render 5 recipe offers
    for i, offer in enumerate(st.session_state.suggestions):
        with st.container(border=True):
            st.markdown(f"#### 🍳 {offer.title}")
            st.write(offer.summary)
            if offer.link:
                st.caption(f"[View Original Source]({offer.link})")
            
            if st.button(f"Generate Recipe: {offer.title}", key=f"btn_{i}"):
                with st.spinner("Preparing detailed instructions..."):
                    final_recipe = None
                    
                    # Try scraping the web page first
                    if offer.link and offer.link.startswith("http"):
                        try:
                            scraped_recipe = scrape_recipe_details(offer.link, model=user_model)
                            if scraped_recipe.ingredients and scraped_recipe.steps:
                                final_recipe = scraped_recipe
                                st.toast("Successfully retrieved original recipe from source! 🎯")
                        except Exception:
                            pass
                    
                    # If scraping fails, use the generative "backup" chef mode
                    if not final_recipe:
                        st.toast("Web source is protected. Chef mode activated! 🧠")
                        generated_recipe = generate_final_recipe(st.session_state.detected_ingredients, offer, model=user_model)
                        final_recipe = ScrapedRecipeDetails(
                            title=generated_recipe.recipe,
                            ingredients=generated_recipe.ingredients_list,
                            steps=generated_recipe.steps,
                            link=offer.link
                        )
                    
                    st.session_state.final_recipe = final_recipe

# --- STEP 3: Display Final Structured Recipe ---
if st.session_state.final_recipe:
    st.write("---")
    st.balloons()
    st.markdown(f"## 🎉 Your Master Recipe: {st.session_state.final_recipe.title}")
    
    if st.session_state.final_recipe.link:
        st.info(
            f"🔗 **Original Source:** [{st.session_state.final_recipe.link}]({st.session_state.final_recipe.link})\n\n"
            f"*Disclaimer: If website protection was triggered, this recipe might be an AI adaptation of the concept. "
            f"For safety and exact baking proportions, we highly recommend double-checking the original link!*"
        )
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### 🛒 Ingredients Needed:")
        for ing in st.session_state.final_recipe.ingredients:
            st.markdown(f"- {ing}")
            
    with col2:
        st.markdown("### 📋 Preparation Steps:")
        for idx, step in enumerate(st.session_state.final_recipe.steps, 1):
            st.markdown(f"**{idx}.** {step}")