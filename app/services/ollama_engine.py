import json
import re
import os
from dotenv import load_dotenv
from openai import OpenAI

# ==========================================
# CONFIGURATION & INITIALIZATION
# ==========================================
load_dotenv(override=True)

MODEL_NAME = "llama-3.3-70b-versatile"
groq_api_key = os.getenv("GROQ_API_KEY")

# Safely initialize Groq Client
if not groq_api_key:
    print("⚠️ WARNING: GROQ_API_KEY is missing. AI extraction will use fallback mode.")
    client = None
else:
    client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=groq_api_key.strip())

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def clean_json_string(text: str):
    """Aggressively finds and extracts the JSON block from the AI's raw text response."""
    try:
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end != 0:
            return text[start:end]
        return text
    except:
        return text

# ==========================================
# CORE AI ENGINE
# ==========================================
def ask_ollama(user_text: str, history: list = None):
    if history is None: 
        history = []
    
    # Fallback if API key is missing (prevents the whole app from crashing)
    if not client: 
        return {"intent": "search", "specific_items": [user_text]}

    # 🚀 THE ULTIMATE ENTERPRISE ERP SYSTEM PROMPT
    SYSTEM_PROMPT = """
    You are the 'Mewar ERP Assistant', a strict, professional, and helpful warehouse AI. 

    CORE GOAL:
    Extract the EXACT product or supplier name from the user's input. 
    If the user asks questions NOT related to inventory, stock, suppliers, or the ERP, you must politely refuse to answer and guide them back to warehouse tasks.

    CRITICAL EXTRACTION RULES (NEVER BREAK THESE):
    1. STRIP NOISE & QUANTITIES: Remove verbs, pronouns, filler words (ka, ke, bhai, dikhao, please), AND quantities. 
       - "10 beering dikhao" -> Extract ONLY "bearing". (Drop the '10').
       - "mujhe 50kg arawali minerals ka stock batao" -> Extract ONLY "arawali minerals".
    2. PRONOUN RESOLUTION: If the user says "iska stock" (its stock) or "who supplies this?", look at the chat history and extract the specific item/supplier they are referring to.
    3. TYPO & SLANG CORRECTION: Fix common spelling errors ('beering' -> 'bearing', 'coniyor' -> 'conveyor', 'vvbelt' -> 'v belt'). Translate local factory slang to formal names if obvious (e.g., 'patta' -> 'belt').
    4. DIMENSION PROTECTION: Keep technical specs exactly the same ('900mm X 4 Ply', '6205 Z'). Do NOT strip numbers that are part of a model code.
    5. MULTIPLE ITEMS: Split multiple requested items into separate strings in the array.
    6. ANTI-HALLUCINATION: NEVER invent or guess item names. Only extract exactly what the user implied.

    INTENT TYPES & STRICT JSON OUTPUT EXAMPLES:

    - 'search' (Checking inventory)
      User: "bhai 50 v belt aur 10 beering dikhao"
      Output: {"intent": "search", "specific_items": ["v belt", "bearing"]}

    - 'supplier_search' (Getting specific supplier info)
      User: "mujhe Arawali minerals ka email batao"
      Output: {"intent": "supplier_search", "specific_items": ["Arawali minerals"]}
      
    - 'search' (Using Context/Pronouns)
      History: User asked about "V Belt". 
      User: "iska supplier kaun hai?"
      Output: {"intent": "search", "specific_items": ["v belt"]}

    - 'chat' (Greetings or polite factory help)
      User: "namaste bhai"
      Output: {"intent": "chat", "message": "नमस्ते! मैं Mewar ERP बॉट हूँ। आज मैं इन्वेंट्री और स्टॉक के साथ आपकी कैसे मदद कर सकता हूँ?"}

    - 'out_of_scope' (Math, general knowledge, or non-ERP chat)
      User: "what is 5+2?" or "tell me a joke"
      Output: {"intent": "chat", "message": "I am an ERP inventory assistant. I can only help you check warehouse stock, item details, and supplier information. What would you like to search for?"}

    Return ONLY a valid JSON object matching the structures above. Do not include markdown formatting or extra text.
    """

    # 🧠 Build the memory context
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Keep only the last 4 messages to save tokens and prevent confusion
    for msg in history[-4:]:  
        if msg.get("role") in ["user", "assistant"]:
            # Extract pure text context, ignoring large JSON UI payloads
            content = msg.get("content") or msg.get("raw_content", "")
            messages.append({"role": msg["role"], "content": content})
            
    # Append the current request
    messages.append({"role": "user", "content": user_text})

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            response_format={ "type": "json_object" },
            temperature=0.0 # Strict zero variance for consistent data extraction
        )
        
        # Parse and clean the output
        raw_output = response.choices[0].message.content
        data = json.loads(clean_json_string(raw_output))
        
        # Failsafe: Ensure 'specific_items' exists so downstream code doesn't crash
        if "specific_items" not in data:
            data["specific_items"] = []
            
        return data
        
    except Exception as e:
        print(f"🔴 AI Engine Error: {e}")
        # Safe fallback passing the raw text to the spell-checker if Groq is down
        return {"intent": "search", "specific_items": [user_text]}