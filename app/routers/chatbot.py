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

    # 🛡️ SHIELD 1: GREETING INTERCEPTOR (Prevents the "Hello -> Lo" bug)
    greetings = ["hello", "hi", "hey", "namaste", "good morning", "gm", "hlo"]
    if low_q in greetings:
        return {"results": [{"type": "chat", "message": "नमस्ते! मैं Mewar ERP बॉट हूँ। आज मैं आपकी कैसे मदद कर सकता हूँ?"}]}
    
    # 🎯 STEP 1: FAST-TRACK (EXACT ID & SUPPLIER CODE)
    sup_match = re.search(r'sup[- \s]?(\d+)', low_q)
    if sup_match:
        num = sup_match.group(1)
        supplier = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_code) IN (:c1, :c2) OR id = :id LIMIT 1"), {"c1": f"sup-{num}", "c2": f"sup{num}", "id": int(num)}).fetchone()
        if supplier:
            inv_items = db.execute(text("SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0"), {"sid": supplier.id}).fetchall()
            return {"results": [{"type": "result", "supplier": {"id": supplier.id, "name": supplier.supplier_name, "code": supplier.supplier_code or "N/A", "email": supplier.email or "N/A", "gstin": supplier.gstin or "N/A"}, "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]}]}

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

    # 🚀 STEP 2: AI INTENT
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")

    # 🏭 STEP 3: MASTER SUPPLIER LOGIC
    supplier_keywords = ["supplier", "suplier", "supllier", "vendor", "party", "kon kon"]
    is_supplier_intent = any(k in low_q for k in supplier_keywords) or intent == "supplier_search"

    if is_supplier_intent:
        noise_words = r'\b(supplier|suplier|supllier|active|details|show|me|ka|ke|ki|batao|kon|hai|list|all|sare|directory|give|the)\b'
        clean_s = re.sub(noise_words, '', low_q).strip()
        if not clean_s or len(clean_s) < 2:
            suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers ORDER BY supplier_name ASC LIMIT 15")).fetchall()
            return {"results": [{"type": "supplier_list", "message": "📋 Active Supplier Directory:", "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code or 'N/A'})"} for s in suppliers]}]}

        s_res = db.execute(text("SELECT * FROM suppliers WHERE LOWER(supplier_name) LIKE :q OR LOWER(supplier_code) = :q2 LIMIT 1"), {"q": f"%{clean_s}%", "q2": clean_s}).fetchall()
        if s_res:
            final_output = []
            for s in s_res:
                inv_items = db.execute(text("SELECT i.name, SUM(CASE WHEN LOWER(t.txn_type) = 'in' THEN t.quantity ELSE -t.quantity END) as current_stock FROM inventories i JOIN stock_transactions t ON i.id = t.inventory_id WHERE t.supplier_id = :sid GROUP BY i.id, i.name HAVING current_stock != 0"), {"sid": s.id}).fetchall()
                final_output.append({"type": "result", "supplier": {"id": s.id, "name": s.supplier_name, "code": s.supplier_code or "N/A", "email": s.email or "N/A", "gstin": s.gstin or "N/A"}, "items": [{"name": row.name, "stock": float(row.current_stock)} for row in inv_items]})
            return {"results": final_output}

    # 📦 STEP 4: SMART INVENTORY SEARCH
    final_output = []
    seen_ids = set()
    raw_targets = ai_data.get("specific_items", [])
    
    # 🛡️ SHIELD 2: Length & Noise Filter (Prevents "Active" and "Lo" bugs)
    search_targets = [t for t in raw_targets if len(str(t)) > 2 and str(t).lower() not in ["active", "kon", "hai", "details", "item", "stock", "hello"]]
    
    if not search_targets:
        clean_q = re.sub(r'\b(chahiye|hai|batao|dikhao|show|me|stock|and|aur|active|details|hello|hi)\b', '', low_q).strip()
        if len(clean_q) > 2: search_targets = [clean_q]

    for target in search_targets:
        inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) LIKE :q LIMIT 11"), {"q": f"%{target.lower()}%"}).fetchall()
        
        # 🛡️ SHIELD 3: Only fuzzy match if the word is long enough
        if not inv_res and len(target) > 3:
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

    if final_output:
        return {"results": final_output}

    return {"results": [{"type": "chat", "message": "I couldn't find that. Please try searching for a specific Item or Supplier."}]}