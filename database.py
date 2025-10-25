# database.py
import sqlite3
from datetime import datetime
import os

def get_db():
    """Get database connection - MUST MATCH init_database() path"""
    if os.name == "nt":  # Windows
        DATA_ROOT = os.path.abspath(r"C:\career_ai_data")
        db_path = os.path.join(DATA_ROOT, "career_ai.db")
    else:  # Linux/Railway
        DATA_ROOT = os.path.abspath("/app/data")
        db_path = os.path.join(DATA_ROOT, "career_ai.db")
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

init_db()
