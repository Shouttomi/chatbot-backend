import os
import urllib.parse
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# 1. Load environment variables from .env (for local) or Vercel Settings (for live)
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 2. Setup the Remote Connection if DATABASE_URL is missing in .env
if not DATABASE_URL:
    # IMPORTANT: If your password has special characters like @, :, or ; 
    # you MUST use quote_plus as shown below:
    user = "u512872665_user"
    password = urllib.parse.quote_plus("a3nQyY7RT;G9")  # Encodes special characters
    host = "193.203.184.201"
    port = "3306"
    dbname = "u512872665_db"
    
    DATABASE_URL = f"mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}"

# 3. Create the engine with 'pool_pre_ping'
# This is critical for remote databases to prevent "MySQL server has gone away" errors
engine = create_engine(
    DATABASE_URL, 
    echo=True,
    pool_pre_ping=True,
    pool_recycle=3600
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 4. Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()







# import os
# from dotenv import load_dotenv
# from sqlalchemy import create_engine
# from sqlalchemy.orm import sessionmaker

# load_dotenv()

# DATABASE_URL = os.getenv("DATABASE_URL")

# if not DATABASE_URL:
#     DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/mewar"

# engine = create_engine(DATABASE_URL, echo=True)

# SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# def get_db():
#     db = SessionLocal()
#     try:
#         yield db
#     finally:
#         db.close()



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