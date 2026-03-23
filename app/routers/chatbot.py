from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user
import re
import difflib
from app.services.ollama_engine import ask_ollama

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()
    
    # 🎯 STEP 1: FAST-TRACK (EXACT ID & SUPPLIER CODE)
    # ---------------------------------------------------------
    sup_match = re.search(r'sup[- \s]?(\d+)', low_q)
    if sup_match:
        num = sup_match.group(1)
        supplier = db.execute(text("""
            SELECT * FROM suppliers 
            WHERE LOWER(supplier_code) IN (:c1, :c2) OR id = :id LIMIT 1
        """), {"c1": f"sup-{num}", "c2": f"sup{num}", "id": int(num)}).fetchone()
        
        if supplier:
            # Fetch inventory for this specific supplier
            inv_items = db.execute(text("""
                SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock
                FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id
                WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0
            """), {"sid": supplier.id}).fetchall()
            
            return {"results": [{
                "type": "result", 
                "supplier": {"id": supplier.id, "name": supplier.supplier_name, "code": supplier.supplier_code or "N/A", "email": supplier.email or "N/A", "gstin": supplier.gstin or "N/A"},
                "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]
            }]}

    if low_q.isdigit():
        inv = db.execute(text("SELECT id, name, classification FROM inventories WHERE id = :id"), {"id": int(low_q)}).fetchone()
        if inv:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = (inv.classification or "").lower()
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            return {"results": [{"type": "result", "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "N/A").upper()}, "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m+f+sf)}]}

    # 🚀 STEP 2: AI INTENT & ANALYTICS
    # ---------------------------------------------------------
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")

    if intent == "analytics" or any(x in low_q for x in ["low stock", "kam stock", "highest stock"]):
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0} for inv in all_inv}
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in": stock_map[t.inventory_id]["Stock"] += qty
                else: stock_map[t.inventory_id]["Stock"] -= qty
        stock_data = list(stock_map.values())
        if "high" in low_q:
            stock_data.sort(key=lambda x: x["Stock"], reverse=True)
            title = "📈 Top 10 Highest Stock Items"
        else:
            stock_data.sort(key=lambda x: x["Stock"])
            title = "📉 Top 10 Lowest Stock Items"
        return {"results": [{"type": "analytics_chart", "title": title, "chart_type": "bar", "data": stock_data[:10]}]}


    # 🏭 STEP 3: MASTER SUPPLIER LOGIC (Handles Typos, General Intents & Inventory)
    # ---------------------------------------------------------
    # Notice we included "suplier", "supllier" (typos) and "active"
    supplier_keywords = ["supplier", "suplier", "supllier", "vendor", "party", "kon kon"]
    is_supplier_intent = any(k in low_q for k in supplier_keywords) or intent == "supplier_search"

    if is_supplier_intent:
        # 1. The "Vacuum" - Strip out all general words and typos
        noise_words = r'\b(supplier|suplier|supllier|active|details|show|me|ka|ke|ki|batao|kon|hai|list|all|sare|directory|give|the)\b'
        clean_s = re.sub(noise_words, '', low_q).strip()
        clean_s = re.sub(r'[^\w\s-]', '', clean_s).strip() # Remove random punctuation

        # 2. If nothing is left (e.g. they just typed "active suplier ki details") -> Show Directory!
        if not clean_s:
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers ORDER BY supplier_name ASC LIMIT 20")).fetchall()
            return {"results": [{"type": "supplier_list", "message": "📋 Active Supplier Directory:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers]}]}

        # 3. If there is a specific name left (e.g. "arawali"), search for it
        s_res = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q OR LOWER(supplier_code) = :q2 LIMIT 5"), {"q": f"%{clean_s}%", "q2": clean_s}).fetchall()
        
        # Fuzzy Fallback
        if not s_res and len(clean_s) > 2:
            all_s = db.execute(text("SELECT id, supplier_name FROM suppliers")).fetchall()
            matches = difflib.get_close_matches(clean_s, [s.supplier_name.lower() for s in all_s], n=1, cutoff=0.4)
            if matches:
                s_res = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) = :n"), {"n": matches[0]}).fetchall()

        # 4. If specific supplier found, fetch their inventory
        if s_res:
            final_output = []
            for s in s_res:
                inv_items = db.execute(text("""
                    SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock
                    FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id
                    WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0
                """), {"sid": s.id}).fetchall()

                final_output.append({
                    "type": "result",
                    "supplier": {"id": s.id, "name": s.supplier_name, "code": s.supplier_code or "N/A", "email": s.email or "N/A", "gstin": s.gstin or "N/A"},
                    "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]
                })
            return {"results": final_output}
        else:
            # If they searched a specific name but it failed, show directory as fallback
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 10")).fetchall()
            return {"results": [{"type": "supplier_list", "message": f"Couldn't find '{clean_s}'. Here are some active suppliers:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers]}]}


    # 📦 STEP 4: SMART INVENTORY SEARCH (Multi-Item)
    # ---------------------------------------------------------
    final_output = []
    seen_ids = set()

    raw_targets = ai_data.get("specific_items", [])
    # Extra safety to ignore typos of supplier
    search_targets = [t for t in raw_targets if not str(t).lower().startswith("suppl") and not str(t).lower().startswith("supli") and str(t).lower() not in ["kon", "hai", "details", "active", "ki"]]
    
    if not search_targets:
        clean_q = re.sub(r'\b(chahiye|hai|batao|dikhao|show|me|stock|and|aur)\b', '', low_q).strip()
        search_targets = re.split(r',| and | aur ', clean_q) if any(x in clean_q for x in [",", " and ", " aur "]) else [clean_q]

    for target in search_targets:
        target = target.strip()
        if len(target) < 2: continue
        
        inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) LIKE :q LIMIT 11"), {"q": f"%{target.lower()}%"}).fetchall()
        if not inv_res:
            all_i = db.execute(text("SELECT name FROM inventories")).fetchall()
            matches = difflib.get_close_matches(target, [i.name.lower() for i in all_i], n=1, cutoff=0.5)
            if matches:
                inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) = :n"), {"n": matches[0]}).fetchall()

        if len(inv_res) == 1:
            inv = inv_res[0]
            if inv.id in seen_ids: continue
            seen_ids.add(inv.id)
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                cls = (inv.classification or "").lower()
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            final_output.append({"type": "result", "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "N/A").upper()}, "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m+f+sf)})
        
        elif 1 < len(inv_res) <= 10:
            final_output.append({"type": "dropdown", "message": f"Found multiple items for '{target}':", "items": [{"id": i.id, "name": i.name} for i in inv_res]})
        
        elif len(inv_res) > 10:
            final_output.append({"type": "chat", "message": f"Too many matches for '{target}'. Please be more specific."})

    if final_output:
        return {"results": final_output}

    return {"results": [{"type": "chat", "message": "I couldn't find that. Try an ID (718), a Code (sup-100), or a name (Bearing)."}]}