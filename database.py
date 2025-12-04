# database.py
import sqlite3
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

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
