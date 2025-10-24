import sqlite3

conn = sqlite3.connect("users.db")
cur = conn.cursor()

cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cur.fetchall()
print("📋 Tables in users.db:")
for t in tables:
    print(" -", t[0])

conn.close()
