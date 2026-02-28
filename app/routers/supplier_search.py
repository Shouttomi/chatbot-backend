from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db

# This defines the variable that main.py is trying to import
router = APIRouter(prefix="/supplier", tags=["Supplier"])
# =====================================================
# 1. SUPPLIER DROPDOWN / SEARCH
# =====================================================
@router.get("/search")
def search_suppliers(
    q: str = Query(..., description="Type supplier name or code"),
    db: Session = Depends(get_db)
):
    rows = db.execute(
        text("""
            SELECT id, supplier_name, supplier_code
            FROM suppliers
            WHERE
                LOWER(supplier_name) LIKE LOWER(:q)
                OR LOWER(supplier_code) LIKE LOWER(:q)
            ORDER BY supplier_name
            LIMIT 20
        """),
        {"q": f"%{q}%"}
    ).fetchall()

    return {
        "results": [
            {
                "id": r.id,
                "name": r.supplier_name,
                "code": r.supplier_code,
                "city": r.city
            }
            for r in rows
        ]
    }


# =====================================================
# 2. SUPPLIER DETAILS BY ID
# =====================================================
@router.get("/details/{supplier_id}")
def supplier_details(
    supplier_id: int,
    db: Session = Depends(get_db)
):
    row = db.execute(
        text("""
            SELECT id, supplier_name, supplier_code, email, gstin
            FROM suppliers
            WHERE id = :id
            LIMIT 1
        """),
        {"id": supplier_id}
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    return {
        "id": row.id,
        "name": row.supplier_name,
        "code": row.supplier_code,
        "email": row.email,
        "gstin": row.gstin
    }


# =====================================================
# 3. SUPPLIER DETAILS BY CODE
# =====================================================
@router.get("/by-code")
def supplier_by_code(
    supplier_code: str = Query(...),
    db: Session = Depends(get_db)
):
    row = db.execute(
        text("""
            SELECT id, supplier_name, supplier_code, email, gstin
            FROM suppliers
            WHERE LOWER(supplier_code) = LOWER(:code)
            LIMIT 1
        """),
        {"code": supplier_code}
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Supplier not found")

    return {
        "id": row.id,
        "name": row.supplier_name,
        "code": row.supplier_code,
        "email": row.email,
        "gstin": row.gstin
    }