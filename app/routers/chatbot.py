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
    
    # 🚀 STEP 1: EXACT STOCK MATCH (Bypass AI for speed)
    exact_match = db.execute(text("""
        SELECT id, name, classification FROM inventories 
        WHERE LOWER(name) = :exact OR id = :id_val
    """), {"exact": low_q, "id_val": int(low_q) if low_q.isdigit() else -1}).fetchone()

    if exact_match:
        inv = exact_match
        txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
        m, f, sf = 0, 0, 0
        cls = str(inv.classification).lower() if inv.classification else ""
        for t in txns:
            val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
            if "machining" in cls: m += val
            elif "semi" in cls: sf += val
            else: f += val
        
        return {"results": [{
            "type": "result",
            "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
            "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
        }]}

    # 🚀 STEP 2: AI INTENT & SUPPLIER LOGIC
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    # 👋 GREETINGS INTERCEPTOR
    greetings = ["hi", "hello", "hey", "good morning", "good evening", "namaste", "how are you"]
    if intent == "greeting" or any(low_q == g or low_q.startswith(g + " ") for g in greetings):
        return {"results": [{"message": "Hello! 👋 I am your Mewar ERP Assistant. I can help you check stock levels, item ledgers, and supplier details. What do you need today?"}]}

    suppliers_found = []
    clean_s = ""

    # 🎯 SNIPER MODE: Catch 'sup-100' or 'sup 100'
    code_match = re.search(r'(sup[-\s]\d+)', low_q)
    if code_match:
        clean_s = code_match.group(1).replace(" ", "-")
        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_code) = :exact LIMIT 1"), {"exact": clean_s}).fetchall()
    
    # 🧹 SWEEPER MODE
    if not suppliers_found:
        noise = r'\b(bhai|kya|status|hai|aaj|what|is|the|stock|for|who|email|gstin|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|supplier|suppliers)\b'
        clean_s = re.sub(noise, '', low_q).strip()
        clean_s = re.sub(r'[^\w\s-]', '', clean_s).strip()
        clean_s = re.sub(r'\s+', ' ', clean_s)

        if clean_s:
            if clean_s.isdigit():
                suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id LIMIT 10"), {"id": int(clean_s)}).fetchall()
            else:
                suppliers_found = db.execute(text("""
                    SELECT * FROM suppliers 
                    WHERE LOWER(supplier_name) LIKE :q OR LOWER(supplier_code) LIKE :q LIMIT 10
                """), {"q": f"%{clean_s}%"}).fetchall()
                
                # 🪄 SPELL-CHECKER
                if not suppliers_found:
                    all_s = db.execute(text("SELECT id, supplier_name FROM suppliers")).fetchall()
                    s_names = {s.supplier_name.lower(): s.id for s in all_s}
                    matches = difflib.get_close_matches(clean_s, s_names.keys(), n=1, cutoff=0.6)
                    if matches:
                        best_match_id = s_names[matches[0]]
                        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id LIMIT 1"), {"id": best_match_id}).fetchall()

    is_supplier_intent = intent in ["supplier_search", "supplier_list"] or any(k in low_q for k in ["email", "gstin", "supplier", "sup-", "sup "])

    if suppliers_found or is_supplier_intent:
        
        # 🟡 CASE A: MULTIPLE SUPPLIERS
        if len(suppliers_found) > 1:
            return {"results": [{
                "type": "supplier_list",
                "message": f"I found multiple suppliers for '{clean_s}'. Please select one:",
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers_found]
            }]}
            
        # 🔵 CASE B: EXACTLY ONE SUPPLIER (Ledger Math)
        elif len(suppliers_found) == 1:
            supplier = suppliers_found[0]
            inventories = db.execute(text("""
                SELECT DISTINCT i.id, i.name, i.classification
                FROM inventories i
                JOIN stock_transactions st ON i.id = st.inventory_id
                WHERE st.supplier_id = :sid
            """), {"sid": supplier.id}).fetchall()

            finish_total, semi_finish_total = 0, 0
            items = []

            for inv in inventories:
                txns = db.execute(text("""
                    SELECT txn_type, ref_type, quantity
                    FROM stock_transactions
                    WHERE inventory_id = :inv_id AND supplier_id = :supplier_id
                """), {"inv_id": inv.id, "supplier_id": supplier.id}).fetchall()

                in_qty, out_qty, finish_in, machining_out = 0, 0, 0, 0

                for t in txns:
                    txn_type = (t.txn_type or "").lower()
                    ref_type = (t.ref_type or "").lower()
                    qty = float(t.quantity or 0)

                    if txn_type == "in" and ref_type != "finish": in_qty += qty
                    if txn_type == "out" and ref_type != "machining": out_qty += qty
                    if txn_type == "in" and ref_type == "finish": finish_in += qty
                    if txn_type == "out" and ref_type == "machining": machining_out += qty

                classification = (inv.classification or "").upper().strip()
                total = in_qty - out_qty

                if total != 0:
                    if classification == "FINISH": finish_total += total
                    else: semi_finish_total += total
                    items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})

            return {"results": [{
                "type": "result", 
                "supplier": {
                    "id": supplier.id,
                    "name": supplier.supplier_name, 
                    "code": getattr(supplier, 'supplier_code', 'N/A'),
                    "email": getattr(supplier, 'email', 'N/A'), 
                    "gstin": getattr(supplier, 'gstin', 'N/A')
                },
                "finish_stock": finish_total,
                "semi_finish_stock": semi_finish_total,
                "items": items,
                "message": f"Details for {supplier.supplier_name}"
            }]}
            
        # 🟡 CASE C: NO SUPPLIER FOUND (Fallback Menu)
        else:
            msg = "Which supplier are you looking for? Please select from the list:" if not clean_s else f"I couldn't find a supplier matching '{clean_s}'. Select from list:"
            all_s = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 5")).fetchall()
            return {"results": [{
                "type": "supplier_list", 
                "message": msg,
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in all_s]
            }]}

    # 🚀 STEP 3: GENERAL INVENTORY SEARCH
    search_targets = ai_data.get("specific_items", [])
    if not search_targets: search_targets = [low_q]
    
    final_output = []
    for target in search_targets:
        t_str = str(target).strip().lower()
        inv_res = db.execute(text("""
            SELECT id, name, classification FROM inventories 
            WHERE LOWER(name) REGEXP :q LIMIT 10
        """), {"q": rf"\b{re.escape(t_str)}\b"}).fetchall()

        if len(inv_res) == 1:
            inv = inv_res[0]
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = str(inv.classification).lower() if inv.classification else ""
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            
            return {"results": [{
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            }]}
            
        elif len(inv_res) > 1:
            final_output.append({
                "type": "dropdown", "message": f"Select an item for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inv_res]
            })
            
    if final_output:
        return {"results": [final_output[0]]}
        
    return {"results": [{"message": "I couldn't find that item in the database."}]}