from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.database import get_db
from app.schemas.chat import ChatRequest
from app.dependencies import get_current_user

from rapidfuzz import process, fuzz
import re

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

# -------------------------------------------------
# HINGLISH MAP (MINIMAL BUT USEFUL)
# -------------------------------------------------
HINGLISH_MAP = {
    "hai kya": "available",
    "milega": "available",
    "milta": "available",
    "kitna": "stock",
    "kitni": "stock",
    "kitne": "stock",
    "dikhao": "show",
    "list dikhao": "show",
    "sab dikhao": "show all",
    "mujhe": "",
    "chahiye": "",
    "ka": "",
    "ki": "",
    "ke": "",
    "ko": "",
    "se": "",
    "maal": "product",
    "saman": "product",
    "namaste": "hi",
    "shukriya": "thanks",
    "alvida": "bye"
}

# -------------------------------------------------
# INTENT LISTS
# -------------------------------------------------
GREETINGS = [
    "hi","hello","hey","hii","helloo",
    "namaste","namaskar","ram ram",
    "good morning","good evening"
]

THANKS = [
    "thanks","thank you","thankyou",
    "thx","shukriya","dhanyavad"
]

BYES = [
    "bye","goodbye","exit","quit",
    "alvida","khuda hafiz"
]

STOP_WORDS = [
    "how","much","many","is","are","am",
    "please","pls","plz",
    "show","give","check","see",
    "for","the","of","in","on","at","to",
    "product","products","item","items",
    "ka","ki","ke","ko","se","hai"
]

ENGLISH_SHOW_WORDS = [
    "show","list","display","view","see",
    "give","provide","get","fetch",
    "show all","list all","display all",
    "inventory","catalog","menu",
    "browse","explore","look","inspect"
]

# -------------------------------------------------
# HELPERS
# -------------------------------------------------
def translate_hinglish(q: str) -> str:
    q = q.lower()
    for h in sorted(HINGLISH_MAP.keys(), key=len, reverse=True):
        q = q.replace(h, HINGLISH_MAP[h])
    return q


def clean_sentence(q: str) -> str:
    q = re.sub(r'[^a-z0-9\s]', ' ', q)
    words = q.split()
    words = [w for w in words if w not in STOP_WORDS]
    return " ".join(words)


def detect_show(q: str):
    q = q.lower()
    words = q.split()
    return any(w in ENGLISH_SHOW_WORDS for w in words)






def get_all_product_names(db: Session):
    rows = db.execute(text("SELECT name FROM inventories")).fetchall()
    return [r[0] for r in rows]


def spell_correct(query: str, db: Session) -> str:
    names = get_all_product_names(db)
    if not names:
        return query

    match = process.extractOne(query, names, scorer=fuzz.partial_ratio)
    if match and match[1] >= 65:
        return match[0]

    return query


# -------------------------------------------------
# MAIN CHATBOT
# -------------------------------------------------
@router.post("/")
def chatbot(request: ChatRequest, db: Session = Depends(get_db), user=Depends(get_current_user)):

 raw_q = request.query.lower().strip()
 raw_q = translate_hinglish(raw_q)

# 1. detect show FIRST
 show_mode = detect_show(raw_q)

# 2. clean sentence
 q = clean_sentence(raw_q)

 if not q:
    return {"message": "Please type product name."}

# 3. ONLY spell correct if NOT show
 if not show_mode:
    q = spell_correct(q, db)


    raw_q = translate_hinglish(raw_q)

    # -------- INTENTS --------
    if any(g in raw_q for g in GREETINGS):
        return {"message": "Hello 👋 I am MEWAR ERP chatbot assistant."}

    if any(t in raw_q for t in THANKS):
        return {"message": "😊 You're welcome!"}

    if any(b in raw_q for b in BYES):
        return {"message": "👋 Goodbye!"}

     # ---------- SHOW DETECTION (BEFORE CLEAN)
    show_mode = detect_show(raw_q)

# ---------- CLEAN AFTER DETECT
    q = clean_sentence(raw_q)

    if not q:
        return {"message": "Please type product name."}

    q = spell_correct(q, db)

# ---------- DROPDOWN MODE
    if show_mode:
        rows = db.execute(
        text("""
            SELECT DISTINCT name
            FROM inventories
            WHERE LOWER(name) LIKE LOWER(:q)
            ORDER BY name
            LIMIT 20
        """),
        {"q": f"%{q}%"}
    ).fetchall()

    if rows:
        return {
            "message": "🔍 Matching Products:",
            "items": [r[0] for r in rows]
        }



    # -------- CLEAN --------
    q = clean_sentence(raw_q)

    if not q:
        return {"message": "Please type product name."}

    # =====================================================
    # STEP 1 — DROPDOWN SEARCH FIRST
    # =====================================================
    search_rows = db.execute(
        text("""
            SELECT DISTINCT name
            FROM inventories
            WHERE LOWER(name) LIKE LOWER(:q)
            ORDER BY name
            LIMIT 20
        """),
        {"q": f"%{q}%"}
    ).fetchall()

    # If user typed product only → DROPDOWN
    if search_rows and not show_mode and len(search_rows) > 1:
        return {
            "message": "🔎 Products:",
            "items": [r[0] for r in search_rows]
        }

    # If show mode → ALWAYS LIST
    if show_mode and search_rows:
        return {
            "message": "📦 Matching Products:",
            "items": [r[0] for r in search_rows]
        }

    # =====================================================
    # STEP 2 — EXACT STOCK ONLY IF SINGLE
    # =====================================================
    q = spell_correct(q, db)

    rows = db.execute(
        text("""
        SELECT i.name,
        COALESCE(SUM(
            CASE
            WHEN LOWER(st.txn_type)='in' THEN st.quantity
            WHEN LOWER(st.txn_type)='out' THEN -st.quantity
            ELSE 0 END),0) AS stock
        FROM inventories i
        LEFT JOIN stock_transactions st ON i.id=st.inventory_id
        WHERE LOWER(i.name) = LOWER(:q)
        GROUP BY i.name
        """),
        {"q": q}
    ).fetchall()

    if not rows:
        return {"message": f"❌ '{q}' not found."}

    name, stock = rows[0]
    stock = int(stock)

    if stock > 0:
        return {"message": f"📦 {name} → ✅ {stock} available"}
    else:
        return {"message": f"📦 {name} → ❌ Out of stock"}



# -------------------------------------------------
# AUTOCOMPLETE
# -------------------------------------------------
@router.post("/suggest")
def suggest_products(request: ChatRequest, db: Session = Depends(get_db)):

    q = request.query.strip()

    if len(q) < 2:
        return {"suggestions": []}

    rows = db.execute(
        text("""
            SELECT DISTINCT name
            FROM inventories
            WHERE LOWER(name) LIKE LOWER(:q)
            ORDER BY name
            LIMIT 10
        """),
        {"q": f"%{q}%"}
    ).fetchall()

    return {"suggestions": [r[0] for r in rows]}