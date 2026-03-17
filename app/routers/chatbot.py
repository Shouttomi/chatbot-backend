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
    
    # 🚀 STEP 1: EXACT STOCK MATCH (ID ONLY)
    exact_match = db.execute(text("""
        SELECT id, name, classification FROM inventories 
        WHERE id = :id_val
    """), {"id_val": int(low_q) if low_q.isdigit() else -1}).fetchone()

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

    # 🎯 SNIPER MODE (Suppliers)
    code_match = re.search(r'(sup[-\s]\d+)', low_q)
    if code_match:
        clean_s = code_match.group(1).replace(" ", "-")
        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_code) = :exact LIMIT 1"), {"exact": clean_s}).fetchall()
    
    # 🧹 SWEEPER & SPELL-CHECKER FOR SUPPLIERS
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
                
                if not suppliers_found:
                    all_s = db.execute(text("SELECT id, supplier_name FROM suppliers")).fetchall()
                    s_names = {s.supplier_name.lower(): s.id for s in all_s}
                    matches = difflib.get_close_matches(clean_s, s_names.keys(), n=1, cutoff=0.5)
                    if matches:
                        best_match_id = s_names[matches[0]]
                        suppliers_found = db.execute(text("SELECT * FROM suppliers WHERE id = :id LIMIT 1"), {"id": best_match_id}).fetchall()

    is_supplier_intent = intent in ["supplier_search", "supplier_list"] or any(k in low_q for k in ["email", "gstin", "supplier", "sup-", "sup "])

    if suppliers_found or is_supplier_intent:
        if len(suppliers_found) > 1:
            return {"results": [{
                "type": "supplier_list",
                "message": f"I found multiple suppliers for '{clean_s}'. Please select one:",
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers_found]
            }]}
        elif len(suppliers_found) == 1:
            supplier = suppliers_found[0]
            inventories = db.execute(text("""
                SELECT DISTINCT i.id, i.name, i.classification
                FROM inventories i JOIN stock_transactions st ON i.id = st.inventory_id
                WHERE st.supplier_id = :sid
            """), {"sid": supplier.id}).fetchall()

            finish_total, semi_finish_total, items = 0, 0, []
            for inv in inventories:
                txns = db.execute(text("""
                    SELECT txn_type, ref_type, quantity FROM stock_transactions
                    WHERE inventory_id = :inv_id AND supplier_id = :supplier_id
                """), {"inv_id": inv.id, "supplier_id": supplier.id}).fetchall()

                in_qty, out_qty = 0, 0
                for t in txns:
                    txn_type, ref_type, qty = (t.txn_type or "").lower(), (t.ref_type or "").lower(), float(t.quantity or 0)
                    if txn_type == "in" and ref_type != "finish": in_qty += qty
                    if txn_type == "out" and ref_type != "machining": out_qty += qty

                total = in_qty - out_qty
                if total != 0:
                    if (inv.classification or "").upper().strip() == "FINISH": finish_total += total
                    else: semi_finish_total += total
                    items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})

            return {"results": [{
                "type": "result", 
                "supplier": {
                    "id": supplier.id, "name": supplier.supplier_name, "code": getattr(supplier, 'supplier_code', 'N/A'),
                    "email": getattr(supplier, 'email', 'N/A'), "gstin": getattr(supplier, 'gstin', 'N/A')
                },
                "finish_stock": finish_total, "semi_finish_stock": semi_finish_total,
                "items": items, "message": f"Details for {supplier.supplier_name}"
            }]}
        else:
            all_s = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 5")).fetchall()
            return {"results": [{
                "type": "supplier_list", 
                "message": "Which supplier are you looking for? Please select from the list:",
                "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in all_s]
            }]}

    # 🚀 STEP 3: GENERAL INVENTORY SEARCH (NINJA CHOPPER + 0.4 SPELL-CHECKER)
    search_targets = ai_data.get("specific_items", [])
    
    # 🧹 Clean the raw string just in case (Notice "and" is NOT in this list anymore!)
    inv_noise = r'\b(chahiye|kya|status|hai|aaj|what|is|the|stock|for|details|ka|ke|bata|batao|do|please|yaar|mujhe|of|show|me|our|item)\b'
    clean_q = re.sub(inv_noise, '', low_q).strip()
    clean_q = re.sub(r'\s+', ' ', clean_q)
    
    if not search_targets: 
        # 🪓 THE NINJA CHOPPER: Slices on "and", "or", and commas!
        if re.search(r'\b(and|or)\b|,', low_q):
            search_targets = [x.strip() for x in re.split(r'\s+and\s+|\s+or\s+|,', clean_q) if x.strip()]
        else:
            search_targets = [clean_q] if clean_q else [low_q]
    else:
        # 🚨 AI SAFETY NET: If Groq missed the typo, force search the raw sentence too!
        if clean_q and clean_q not in search_targets:
            search_targets.append(clean_q)
    
    final_output = []
    seen_ids = set() # Prevent duplicate cards

    for target in search_targets:
        t_str = str(target).strip()
        if not t_str or len(t_str) < 2: continue
            
        inv_res = db.execute(text("""
            SELECT id, name, classification FROM inventories 
            WHERE LOWER(name) LIKE :q OR id = :id_val LIMIT 10
        """), {
            "q": f"%{t_str}%", 
            "id_val": int(t_str) if t_str.isdigit() else -1
        }).fetchall()

        # 🪄 THE NEW 0.4 CUTOFF SPELL-CHECKER
        if not inv_res:
            all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
            
            # Map items to a list to prevent accidental overwrites
            inv_map = {}
            for i in all_inv:
                c_name = str(i.name).lower().strip()
                if c_name not in inv_map: inv_map[c_name] = []
                inv_map[c_name].append(i)
                
            # 🔥 Super forgiving 0.4 cutoff for extreme typos like "vvbelt" or "coniyor"
            matches = difflib.get_close_matches(t_str, inv_map.keys(), n=5, cutoff=0.4)
            
            if matches:
                inv_res = []
                for m in matches: inv_res.extend(inv_map[m])

        # Filter out items we already generated a card for
        inv_res = [i for i in inv_res if i.id not in seen_ids]

        if len(inv_res) == 1:
            inv = inv_res[0]
            seen_ids.add(inv.id)
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = str(inv.classification).lower() if inv.classification else ""
            for t in txns:
                val = float(t.quantity or 0) * (1 if str(t.txn_type).lower() == "in" else -1)
                if "machining" in cls: m += val
                elif "semi" in cls: sf += val
                else: f += val
            
            final_output.append({
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": cls.upper()},
                "machining_stock": m, "finish_stock": f, "semi_finish_stock": sf, "total_stock": (m + f + sf)
            })
            
        elif len(inv_res) > 1:
            final_output.append({
                "type": "dropdown", "message": f"Select an item for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inv_res]
            })
            
    if final_output:
        return {"results": final_output}
        
    # 🆘 THE SUGGESTION MENU (If everything fails / gibberish is typed)
    suggestions = db.execute(text("SELECT id, name FROM inventories LIMIT 5")).fetchall()
    
    if suggestions:
        return {"results": [{
            "type": "dropdown",
            "message": "I couldn't find exactly what you typed. Did you mean one of these?",
            "items": [{"id": s.id, "name": s.name} for s in suggestions]
        }]}
        
    return {"results": [{"message": "I couldn't find that item in the database."}]}