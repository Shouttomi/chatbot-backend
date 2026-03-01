import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/mewar"

engine = create_engine(DATABASE_URL, echo=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# import urllib.parse
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker

# password = urllib.parse.quote_plus("a3nQyY7RT;G9")

# DATABASE_URL = f"mysql+pymysql://u512872665_user:{password}@127.0.0.1:3306/u512872665_db"

# engine = create_engine(DATABASE_URL, echo=True)

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()