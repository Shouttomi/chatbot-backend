import streamlit as st
import requests

# ---------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------
API_URL = "http://127.0.0.1:8000/chatbot/"
PAGE_TITLE = "Mewar ERP Assistant"
PAGE_ICON = "🏭"

st.set_page_config(page_title=PAGE_TITLE, page_icon=PAGE_ICON)

# ---------------------------------------------------------
# CSS STYLING (Optional: Makes chat look cleaner)
# ---------------------------------------------------------
st.markdown("""
<style>
    .stButton>button {
        width: 100%;
        border-radius: 20px;
        border: 1px solid #ddd;
        background-color: #f0f2f6;
    }
    .stButton>button:hover {
        border-color: #FF4B4B;
        color: #FF4B4B;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# SESSION STATE (Chat History)
# ---------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant", "content": "Hello! 👋 I am your Mewar ERP Assistant.\n\nTry asking: **'supplier details'**, **'inventories Stock'**"}
    ]

# Helper to handle button clicks (for dropdowns/suggestions)
def handle_click(item_name):
    # Add user selection to history
    st.session_state.messages.append({"role": "user", "content": item_name})
    # Force a rerun to process this new message immediately
    st.rerun()

# ---------------------------------------------------------
# UI LAYOUT
# ---------------------------------------------------------
st.title(f"{PAGE_ICON} {PAGE_TITLE}")

# 1. DISPLAY CHAT HISTORY
for i, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        
        # Check if this message has interactive options (Buttons)
        if "options" in msg and msg["options"]:
            # Create a container for buttons
            st.write("👇 **Select an option:**")
            
            # Create columns for a grid layout (3 buttons per row)
            options = msg["options"]
            num_columns = 3
            rows = [options[i:i + num_columns] for i in range(0, len(options), num_columns)]
            
            for row in rows:
                cols = st.columns(num_columns)
                for idx, option_text in enumerate(row):
                    # Unique key for every button using message index and option index
                    if cols[idx].button(option_text, key=f"btn_{i}_{option_text}"):
                        handle_click(option_text)

# 2. CHAT INPUT
if prompt := st.chat_input("Type your query..."):
    
    # A. Append User Message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # B. Get Bot Response
    with st.chat_message("assistant"):
        with st.spinner("Analyzing Database..."):
            try:
                # Call FastAPI Backend
                response = requests.post(API_URL, json={"query": prompt})
                
                if response.status_code == 200:
                    data = response.json()
                    
                    bot_text = data.get("message", "I didn't understand that.")
                    
                    # Check for Dropdown items or Suggestions
                    options = []
                    if "items" in data and isinstance(data["items"], list):
                        # Ensure we only grab strings (names)
                        options = [item for item in data["items"] if isinstance(item, str)]
                        # If items are dicts (rare), extract names
                        if not options and len(data["items"]) > 0 and isinstance(data["items"][0], dict):
                             options = [item.get("name", "Unknown") for item in data["items"]]

                    # Display the text immediately
                    st.markdown(bot_text)
                    
                    # Store response in history (including options if any)
                    msg_data = {"role": "assistant", "content": bot_text}
                    if options:
                        msg_data["options"] = options
                    
                    st.session_state.messages.append(msg_data)
                    
                    # If we have buttons, we rerun to show them immediately in the loop above
                    if options:
                        st.rerun()

                else:
                    err_msg = f"❌ Server Error: {response.status_code}"
                    st.error(err_msg)
                    st.session_state.messages.append({"role": "assistant", "content": err_msg})

            except Exception as e:
                err_msg = f"❌ **Connection Failed!**\nMake sure your backend is running (`uvicorn main:app --reload`).\n\nError: {e}"
                st.error(err_msg)
                st.session_state.messages.append({"role": "assistant", "content": err_msg})