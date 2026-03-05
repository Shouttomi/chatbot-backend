from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user

# --- IMPORT OLLAMA ENGINE ---
from app.services.ollama_engine import ask_ollama
from rapidfuzz import process, fuzz

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

GREETINGS = ["hi", "hello", "hey", "namaste", "namaskar", "ram ram"]

@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):
    raw_q = request.query.strip()
    low_q = raw_q.lower()

    # =========================================================
    # 1. GREETING CHECK
    # =========================================================
    words = low_q.split()
    if any(g in words for g in GREETINGS) and len(words) <= 2:
        return {"message": "Hello! 🙏 I am the Mewar ERP AI. How can I help you today?"}

    # =========================================================
    # 2. THE ERP FAILSAFE: DATABASE FIRST, AI SECOND
    # =========================================================
    # We check the inventory table first. If a match exists, we bypass AI guessing.
    direct_inv_check = db.execute(text("""
        SELECT id FROM inventories WHERE LOWER(name) LIKE LOWER(:q) LIMIT 1
    """), {"q": f"%{low_q}%"}).fetchall()

    if direct_inv_check and "supplier" not in low_q:
        # 🟢 DIRECT HIT: Force inventory search to avoid AI supplier errors
        intent = "search"
        products = [low_q]
    else:
        # 🟡 AI FALLBACK: Used for complex questions or supplier lookups
        ai_data = ask_ollama(raw_q)
        intent = ai_data.get("intent", "search")
        products = ai_data.get("products", [])

    # =========================================================
    # FEATURE 1: SHOW ALL SUPPLIERS
    # =========================================================
    if intent == "supplier_list" or low_q == "supplier":
        suppliers = db.execute(text("SELECT id, supplier_name FROM suppliers LIMIT 50")).fetchall()
        return {
            "type": "supplier_list",
            "message": "Active Suppliers Directory:",
            "suppliers": [{"id": s.id, "name": s.supplier_name} for s in suppliers]
        }

    if not products and not low_q.startswith("supplier "):
        return {"message": "Please specify the items or supplier you are looking for."}

    # =========================================================
    # FEATURE 2: SUPPLIER SMART SEARCH
    # =========================================================
    if intent == "supplier_search" or low_q.startswith("supplier "):
        q = str(products[0]).strip().lower() if products else low_q.replace("supplier", "").strip()
        
        # Find the Supplier (Increased to 10 for better visibility)
        if q.isdigit():
            suppliers = db.execute(text("""
                SELECT id, supplier_name, supplier_code, email, gstin
                FROM suppliers WHERE id = :id LIMIT 10
            """), {"id": int(q)}).fetchall()
        else:
            suppliers = db.execute(text("""
                SELECT id, supplier_name, supplier_code, email, gstin
                FROM suppliers 
                WHERE LOWER(supplier_name) LIKE LOWER(:q) OR LOWER(supplier_code) LIKE LOWER(:q)
                ORDER BY supplier_name LIMIT 10
            """), {"q": f"%{q}%"}).fetchall()

        if len(suppliers) > 1:
            return {
                "type": "dropdown",
                "items": [{"id": s.id, "name": s.supplier_name, "code": s.supplier_code} for s in suppliers]
            }
        
        if not suppliers:
            return {"message": f"Supplier '{q}' not found."}

        # --- GET SUPPLIER INVENTORY ---
        supplier = suppliers[0]
        inventories = db.execute(text("SELECT id, name, classification FROM inventories ORDER BY name")).fetchall()
        
        finish_total, semi_finish_total, items = 0, 0, []

        for inv in inventories:
            txns = db.execute(text("""
                SELECT txn_type, ref_type, quantity FROM stock_transactions
                WHERE inventory_id = :inv_id AND supplier_id = :supplier_id
            """), {"inv_id": inv.id, "supplier_id": supplier.id}).fetchall()

            in_qty, out_qty = 0, 0
            for t in txns:
                qty = float(t.quantity or 0)
                if t.txn_type.lower() == "in": in_qty += qty
                if t.txn_type.lower() == "out": out_qty += qty

            total = in_qty - out_qty
            if total != 0:
                classification = (inv.classification or "").upper().strip()
                if classification == "FINISH" or not classification: finish_total += total
                else: semi_finish_total += total
                items.append({"inventory_id": inv.id, "name": inv.name, "stock": total})

        return {
            "type": "result",
            "supplier": {"id": supplier.id, "name": supplier.supplier_name, "code": supplier.supplier_code},
            "finish_stock": finish_total, "semi_finish_stock": semi_finish_total, "items": items
        }

    # =========================================================
    # FEATURE 3: STANDARD INVENTORY MULTI-SEARCH
    # =========================================================
    final_output = []
    
    for p_name in products:
        target = str(p_name).strip().lower()
        
        if target.isdigit():
            inventories = db.execute(text("SELECT * FROM inventories WHERE id = :id"), {"id": int(target)}).fetchall()
        else:
            # 🚀 INCREASED LIMIT TO 10 FOR DROPDOWN 🚀
            inventories = db.execute(text("""
                SELECT id, name, classification, unit, placement, height, width, thikness
                FROM inventories WHERE LOWER(name) LIKE LOWER(:q) ORDER BY name LIMIT 10
            """), {"q": f"%{target}%"}).fetchall()

        # PROCESS RESULTS
        if len(inventories) > 1:
            final_output.append({
                "product_requested": target,
                "type": "dropdown",
                "message": f"Found {len(inventories)} matches for '{target}':",
                "items": [{"id": i.id, "name": i.name} for i in inventories]
            })
        elif len(inventories) == 1:
            inv = inventories[0]
            txns = db.execute(text("SELECT txn_type, quantity FROM stock_transactions WHERE inventory_id = :id"), {"id": inv.id}).fetchall()
            
            total = sum(float(t.quantity) if t.txn_type.lower() == "in" else -float(t.quantity) for t in txns)
            final_output.append({
                "type": "result",
                "inventory": {"id": inv.id, "name": inv.name, "classification": (inv.classification or "").upper()},
                "stock": {"total": total}
            })
        else:
            # FUZZY SUGGESTIONS (Auto-fallback)
            all_rows = db.execute(text("SELECT name FROM inventories")).fetchall()
            names = [r[0] for r in all_rows]
            closest = process.extract(target, names, limit=10)
            final_output.append({
                "product_requested": target,
                "message": f"❌ '{target}' not found. Did you mean:",
                "suggestions": [m[0] for m in closest]
            })

    return {"results": final_output}