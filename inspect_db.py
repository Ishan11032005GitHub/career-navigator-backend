import sqlite3
import os

db_path = "users.db"

print(f"🔍 Checking if database exists at: {os.path.abspath(db_path)}")

if not os.path.exists(db_path):
    print("❌ Database file not found!")
else:
    print("✅ Database file found!")

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        print("✅ Connected successfully!")

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("\n📋 Tables found:", tables if tables else "None")

        if tables:
            for t in tables:
                print(f"\n🧾 Preview of {t[0]}:")
                cursor.execute(f"SELECT * FROM {t[0]} LIMIT 5;")
                rows = cursor.fetchall()
                if rows:
                    for r in rows:
                        print("  ", r)
                else:
                    print("  (no rows)")

    except Exception as e:
        print("❌ Error:", e)

    finally:
        conn.close()
