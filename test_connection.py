from sqlalchemy import text
from app.db.database import engine

def test_db():
    print("⏳ Attempting to connect to the database...")
    try:
        # Try to open a connection
        with engine.connect() as connection:
            # Run a simple query to verify it works
            result = connection.execute(text("SELECT VERSION()"))
            version = result.fetchone()
            print(f"✅ SUCCESS! Connected to MySQL Database.")
            print(f"📊 Database Version: {version[0]}")
    except Exception as e:
        print(f"❌ FAILED TO CONNECT.")
        print(f"Error Details: {e}")

if __name__ == "__main__":
    test_db()