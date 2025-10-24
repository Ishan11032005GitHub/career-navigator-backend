from database import get_db

conn = get_db()
rows = conn.execute("PRAGMA database_list;").fetchall()
for row in rows:
    print(f"✅ Connected to DB at: {row['file']}")
conn.close()
