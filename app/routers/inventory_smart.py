from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db

router = APIRouter(prefix="/inventory", tags=["Inventory Smart Search"])


@router.post("/search")
def inventory_smart_search(query: str, db: Session = Depends(get_db)):

    q = str(query).lower().strip()

    # =========================
    # STEP 1 : FIND INVENTORIES
    # =========================

    # ---- IF USER TYPES "inventory" → SHOW ALL ----
    if q == "inventory":
        inventories = db.execute(
            text("""
                SELECT id, name, classification,
                       unit, placement, height, width, thikness
                FROM inventories
                ORDER BY name
                LIMIT 30
            """)
        ).fetchall()

    # ---- IF USER TYPES NUMBER → ID SEARCH ----
    elif q.isdigit():
        inventories = db.execute(
            text("""
                SELECT id, name, classification,
                       unit, placement, height, width, thikness
                FROM inventories
                WHERE id = :id
            """),
            {"id": int(q)}
        ).fetchall()

    # ---- NAME SEARCH ----
    else:
        inventories = db.execute(
            text("""
                SELECT id, name, classification,
                       unit, placement, height, width, thikness
                FROM inventories
                WHERE LOWER(name) LIKE LOWER(:q)
                ORDER BY name
                LIMIT 20
            """),
            {"q": f"%{q}%"}
        ).fetchall()

    # =========================
    # MULTIPLE → DROPDOWN
    # =========================
    if len(inventories) > 1:
        return {
            "type": "dropdown",
            "items": [
                {
                    "id": inv.id,
                    "name": inv.name,
                    "classification": inv.classification,
                    "unit": inv.unit
                }
                for inv in inventories
            ]
        }

    # =========================
    # NONE
    # =========================
    if not inventories:
        return {"message": "Inventory not found"}

    # =========================
    # SINGLE → FULL RESULT
    # =========================
    inv = inventories[0]

    # =========================
    # STOCK TRANSACTIONS
    # =========================
    txns = db.execute(
        text("""
            SELECT txn_type, ref_type, quantity
            FROM stock_transactions
            WHERE inventory_id = :inv_id
        """),
        {"inv_id": inv.id}
    ).fetchall()

    in_qty = 0
    out_qty = 0
    finish_in = 0
    machining_out = 0

    for t in txns:
        txn_type = (t.txn_type or "").lower()
        ref_type = (t.ref_type or "").lower()
        qty = float(t.quantity or 0)

        if txn_type == "in" and ref_type != "finish":
            in_qty += qty

        if txn_type == "out" and ref_type != "machining":
            out_qty += qty

        if txn_type == "in" and ref_type == "finish":
            finish_in += qty

        if txn_type == "out" and ref_type == "machining":
            machining_out += qty

    classification = (inv.classification or "").upper().strip()

    machining_stock = 0
    semi_finish_stock = 0
    finish_stock = 0
    total = in_qty - out_qty

    # =========================
    # CLASSIFICATION LOGIC
    # =========================
    if classification in ["", "FINISH", "NULL"]:
        finish_stock = in_qty - out_qty

    elif classification == "SEMI_FINISH":
        final_mc = machining_out - finish_in
        final_fnsh = finish_in - out_qty
        semifinish = in_qty - out_qty - final_mc - final_fnsh

        machining_stock = final_mc
        finish_stock = final_fnsh
        semi_finish_stock = semifinish

    else:
        finish_stock = in_qty - finish_in

    # =========================
    # FINAL RESPONSE
    # =========================
    return {
        "type": "result",
        "inventory": {
            "id": inv.id,
            "name": inv.name,
            "classification": classification,
            "unit": inv.unit,
            "placement": inv.placement,
            "height": inv.height,
            "width": inv.width,
            "thickness": inv.thikness   # DB column = thikness
        },
        "machining_stock": machining_stock,
        "finish_stock": finish_stock,
        "semi_finish_stock": semi_finish_stock,
        "total_stock": total
    }