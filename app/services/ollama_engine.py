import ollama
import json
import re

# --- CONFIGURATION ---
MODEL_NAME = "gemma3:4b"

# --- 1. SETUP OLLAMA CLIENT ---
# We create this globally so it is ready when the server starts
try:
    client = ollama.Client(host='http://localhost:11434')
except Exception as e:
    print(f"⚠️ Warning: Could not connect to Ollama. Ensure it is running. {e}")
    client = None

# --- 2. HELPER FUNCTIONS ---
def clean_json_string(text: str):
    """Extracts JSON from text if the model adds markdown."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else text

def ask_ollama(user_text: str):
    """
    Extracts Intent and a LIST of products.
    Input: "Check stock for bearing and v belt"
    Output: {"intent": "stock", "products": ["bearing", "v belt"]}
    """
    SYSTEM_PROMPT = """
    You are an ERP Assistant. extract USER INTENT and PRODUCT NAMES.
    
    RULES:
    1. If user asks for multiple items (connected by 'and', '&', ','), split them.
    2. VALID INTENTS: "stock", "search", "greet", "bye".
    
    OUTPUT JSON FORMAT:
    {"intent": "...", "products": ["item1", "item2"]}
    
    Example: "bearing 6205 aur v belt ka stock"
    JSON: {"intent": "stock", "products": ["bearing 6205", "v belt"]}
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
        # Fallback: Return the whole text as one product
        return {"intent": "search", "products": [user_text]}
    