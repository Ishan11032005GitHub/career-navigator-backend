import sqlite3

conn = sqlite3.connect("users.db")
cur = conn.cursor()
cur.execute("SELECT email, username, password FROM users")
rows = cur.fetchall()

print("📋 Users in database:")
for row in rows:
    print(row)

conn.close()
