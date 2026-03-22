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
    
    # 🎯 STEP 1: EXACT CODE & ID DETECTOR (The "Fast Track")
    
    # Check for Supplier Code (e.g., sup-100 or sup 100)
    sup_code_match = re.search(r'sup[-\s](\d+)', low_q)
    if sup_code_match:
        code_num = sup_code_match.group(1)
        # Search for exact supplier_code or ID
        supplier = db.execute(text("""
            SELECT * FROM suppliers 
            WHERE LOWER(supplier_code) = :c OR id = :id 
            LIMIT 1
        """), {"c": f"sup-{code_num}", "id": int(code_num)}).fetchone()
        
        if supplier:
            return {"results": [{
                "type": "result", 
                "supplier": {
                    "id": supplier.id, 
                    "name": supplier.supplier_name, 
                    "code": supplier.supplier_code,
                    "email": supplier.email or "N/A", 
                    "gstin": supplier.gstin or "N/A"
                },
                "message": f"Found Supplier: {supplier.supplier_name}"
            }]}

    # Check for Inventory ID (e.g., "718" or "item 718")
    id_match = re.search(r'^(\d+)$|^item\s+(\d+)$', low_q)
    if id_match:
        target_id = int(id_match.group(1) or id_match.group(2))
        inv = db.execute(text("SELECT id, name, classification FROM inventories WHERE id = :id"), {"id": target_id}).fetchone()
        if inv:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = (inv.classification or "").lower()
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

    # 🚀 STEP 2: AI INTENT (If no exact ID/Code match)
    ai_data = ask_ollama(raw_q, getattr(request, "history", []))
    intent = ai_data.get("intent", "search")
    
    # 📊 STEP 3: ANALYTICS
    if intent == "analytics" or any(x in low_q for x in ["low stock", "kam stock"]):
        all_inv = db.execute(text("SELECT id, name, classification FROM inventories")).fetchall()
        all_txns = db.execute(text("SELECT inventory_id, txn_type, quantity FROM stock_transactions")).fetchall()
        stock_map = {inv.id: {"Name": inv.name, "Stock": 0.0} for inv in all_inv}
        for t in all_txns:
            if t.inventory_id in stock_map:
                qty = float(t.quantity or 0)
                if str(t.txn_type).lower() == "in": stock_map[t.inventory_id]["Stock"] += qty
                else: stock_map[t.inventory_id]["Stock"] -= qty
        stock_data = list(stock_map.values())
        stock_data.sort(key=lambda x: x["Stock"])
        return {"results": [{"type": "analytics_chart", "title": "📉 Low Stock Report", "chart_type": "bar", "data": stock_data[:10]}]}

    # 🚀 STEP 4: GENERAL SUPPLIER & INVENTORY SEARCH
    final_output = []
    
    # Check if user asked for a list of suppliers
    if any(x in low_q for x in ["supplier list", "kon kon hai", "all suppliers"]):
        suppliers = db.execute(text("SELECT id, supplier_name, supplier_code FROM suppliers LIMIT 15")).fetchall()
        return {"results": [{
            "type": "supplier_list",
            "message": "📋 Supplier Directory:",
            "suppliers": [{"id": s.id, "name": f"{s.supplier_name} ({s.supplier_code})"} for s in suppliers]
        }]}

    # Standard Item Search (Fuzzy)
    raw_targets = ai_data.get("specific_items", [])
    search_targets = [t for t in raw_targets if not str(t).lower().startswith("suppl")]
    if not search_targets: search_targets = [re.sub(r'\b(chahiye|hai|show|me|stock)\b', '', low_q).strip()]

    for target in search_targets:
        if len(target) < 2: continue
        inv_res = db.execute(text("SELECT id, name, classification FROM inventories WHERE LOWER(name) LIKE :q LIMIT 5"), {"q": f"%{target.lower()}%"}).fetchall()
        for inv in inv_res:
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            m, f, sf = 0, 0, 0
            cls = (inv.classification or "").lower()
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

    return {"results": final_output if final_output else [{"type": "chat", "message": "I couldn't find that. Please try an ID (718), a Code (sup-100), or a name (Bearing)."}]}