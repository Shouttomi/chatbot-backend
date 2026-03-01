import ollama
import json
import re
import os # Add this
from dotenv import load_dotenv # Add this

load_dotenv() # Load the .env file

# --- CONFIGURATION ---
MODEL_NAME = "gemma3:4b"

# --- 1. SETUP OLLAMA CLIENT ---
try:
    # Read securely from .env
    ollama_api_key = os.getenv("OLLAMA_API_KEY")

    client = ollama.Client(
        host='https://ollama.com',
        headers={'Authorization': f'Bearer {ollama_api_key}'}
    )
    print("☁️ Connected to Ollama Cloud!")

except Exception as e:
    print(f"⚠️ Warning: Could not connect to Ollama. {e}")
    client = None

# --- 2. HELPER FUNCTIONS ---
def clean_json_string(text: str):
    """Extracts JSON from text if the model adds markdown."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text

def ask_ollama(user_text: str):
    """
    Enhanced extraction for multi-search and supplier intents.
    """
    SYSTEM_PROMPT = """
    You are an ERP Assistant. Extract the USER INTENT and a LIST of exact PRODUCT/SUPPLIER NAMES.

    RULES FOR EXTRACTION:
    1. VALID INTENTS: 
       - "stock": asking for quantity/availability of items.
       - "search": looking for item details.
       - "supplier_list": if the user ONLY types "supplier", "all suppliers", or "supplier list".
       - "supplier_search": if the user asks for a specific supplier by ID or name (e.g., "supplier 1", "Mewar Supp").
       - "greet": greetings.
    
    2. EXTRACTION: Extract the core product or supplier name/ID into the "products" list. 
       If the user says "supplier 1", extract "1". If "supplier Mewar", extract "Mewar".

    OUTPUT JSON FORMAT:
    {"intent": "...", "products": ["item1"]}

    EXAMPLES:
    User: "bearing aur v belt"
    JSON: {"intent": "search", "products": ["bearing", "v belt"]}
    
    User: "supplier"
    JSON: {"intent": "supplier_list", "products": []}
    
    User: "supplier 1"
    JSON: {"intent": "supplier_search", "products": ["1"]}
    """

    if not client:
        print("🔴 Error: Ollama client is not connected.")
        return {"intent": "search", "products": [user_text]}

    try:
        response = client.chat(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ]
        )
        
        raw_text = response["message"]["content"]
        cleaned_text = clean_json_string(raw_text)
        return json.loads(cleaned_text)

    except Exception as e:
        print(f"🔴 AI Error: {e}")
        return {"intent": "search", "products": [user_text]}