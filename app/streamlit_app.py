import streamlit as st
import requests
import pandas as pd

# ==========================================
# 🚀 STRICTLY LOCALHOST CONFIGURATION
# ==========================================
API_BASE = "https://mewar-erp.vercel.app"
CHAT_URL = f"{API_BASE}/chatbot/"

st.set_page_config(page_title="Mewar ERP AI", page_icon="🧠", layout="centered")

# --- SESSION STATE INITIALIZATION ---
if "messages" not in st.session_state: st.session_state.messages = []
if "next_query" not in st.session_state: st.session_state.next_query = None

def set_next_query(query_text):
    st.session_state.next_query = query_text

# ==========================================
# CENTRALIZED UI RENDERER
# ==========================================
def render_bot_response(data, msg_idx):
    if "error" in data:
        st.error(f"🔌 {data['error']}")
        return
    if "detail" in data:
        st.error(f"🔴 Access Error: {data['detail']}")
        return

    results_list = data.get("results", [data])

    for res in results_list:
        res_type = res.get("type")

        # 🟢 CASE 1: EXACT STOCK MATCH
        if res_type == "result" and "inventory" in res:
            inv = res["inventory"]
            st.success(f"📦 **{inv['name']}**")
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Stock", res.get("total_stock", 0))
            c2.metric("Finish", res.get("finish_stock", 0))
            c3.metric("Semi-Finish", res.get("semi_finish_stock", 0))
            c4.metric("Machining", res.get("machining_stock", 0))
            
            st.caption(f"Item ID: #{inv['id']} | Category: {inv.get('classification', 'N/A')}")
        
        # 🔵 CASE 2: SUPPLIER MATCH 
        elif res_type == "result" and "supplier" in res:
            sup = res["supplier"]
            st.info(f"🏭 **{sup['name']}**")
            
            code = sup.get('code', 'N/A')
            email = sup.get('email', 'N/A')
            gstin = sup.get('gstin', 'N/A')
            mobile = sup.get('mobile', 'N/A')
            city = sup.get('city', 'N/A')
            state = sup.get('state', 'N/A')
            
            st.markdown(f"**Code:** {code}  \n**Mobile:** {mobile}  \n**Email:** {email}  \n**Location:** {city}, {state}  \n**GSTIN:** {gstin}")
            
            if "items" in res:
                st.write("---")
                items = res.get("items", [])
                if items:
                    st.write("**📦 Inventory from this Supplier:**")
                    for item in items:
                        st.write(f"- {item.get('name')}: **{item.get('stock')}** in stock")
                else:
                    st.info("📦 No active inventory currently in stock from this supplier.")
            
        # 🟡 CASE 3: DROPDOWN MENU
        elif res_type == "dropdown":
            st.warning(res.get("message", "Select an item:"))
            cols = st.columns(2)
            for i, item in enumerate(res.get("items", [])):
                button_label = f"🔎 {item['name']} (#{item['id']})"
                cols[i % 2].button(
                    button_label, 
                    key=f"btn_{item['id']}_{msg_idx}_{i}", 
                    on_click=set_next_query, 
                    args=(str(item['id']),) 
                )
                
        # 🟡 CASE 4: SUPPLIER LIST MENU
        elif res_type == "supplier_list":
            st.warning(res.get("message", "Select a supplier:"))
            for i, s in enumerate(res.get("suppliers", [])):
                st.button(
                    f"🏭 {s['name']}", 
                    key=f"sup_{s['id']}_{msg_idx}_{i}", 
                    on_click=set_next_query, 
                    args=(s['name'],)
                )

        # 📊 CASE 5: MANAGER ANALYTICS CHARTS
        elif res_type == "analytics_chart":
            st.subheader(res.get("title", "📊 Analytics Report"))
            df = pd.DataFrame(res.get("data", []))
            if not df.empty:
                st.dataframe(df, use_container_width=True, hide_index=True)
                if res.get("chart_type") == "bar":
                    st.write("---")
                    st.bar_chart(df.set_index("Name")["Stock"])
            else:
                st.info("No data available for this report.")
        
        # 💬 CASE 6: Simple Text (Chat/Errors)
        elif "message" in res and not res_type:
            st.write(res["message"])
        elif res_type == "chat":
            st.write(res["message"])

# ==========================================
# PAGE: CHATBOT INTERFACE
# ==========================================
with st.sidebar:
    st.header("Admin Panel")
    st.write("Logged in as: **Local Dev**")
    st.divider()
    if st.button("🗑️ Clear Chat History"):
        st.session_state.messages = []
        st.rerun()
    st.caption("Mewar ERP AI - Testing Mode")

st.title("ERP Intelligence 🧠")

def ask_erp(query):
    # Removed the Authorization header entirely
    headers = {"Content-Type": "application/json"}
    history = [{"role": m["role"], "content": m.get("raw_content", "")} for m in st.session_state.messages]
    try:
        r = requests.post(CHAT_URL, json={"query": query, "history": history}, headers=headers)
        return r.json()
    except Exception as e: 
        return {"error": f"FastAPI Connection Failed. {str(e)}"}

# Render Chat History
for idx, msg in enumerate(st.session_state.messages):
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant" and "data" in msg:
            render_bot_response(msg["data"], idx)
        else:
            st.markdown(msg.get("raw_content", ""))

u_input = st.chat_input("Ask me anything about your inventory...")
final_query = u_input or st.session_state.next_query

if final_query:
    st.session_state.next_query = None 
    
    with st.chat_message("user"):
        st.markdown(final_query)
    st.session_state.messages.append({"role": "user", "raw_content": final_query})
    
    data = ask_erp(final_query)
    
    with st.chat_message("assistant"):
        render_bot_response(data, len(st.session_state.messages))
        st.session_state.messages.append({
            "role": "assistant", 
            "data": data, 
            "raw_content": data.get("message", "Processed.")
        })