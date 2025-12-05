# database.py
import os
import sqlite3
import logging
from dotenv import load_dotenv

load_dotenv()

# Single source of truth for DATA_ROOT and DB_PATH
if os.name == "nt":
    DEFAULT_DATA_ROOT = r"C:\career_ai_data"
else:
    DEFAULT_DATA_ROOT = "/app/data"

DATA_ROOT = os.path.abspath(os.getenv("DATA_ROOT", DEFAULT_DATA_ROOT))
DB_PATH = os.path.join(DATA_ROOT, "career_ai.db")


def get_db():
    """
    Open a new SQLite connection to the SAME DB used in main.py.

    - Uses /app/data/career_ai.db on Railway
    - Uses C:\career_ai_data\career_ai.db on Windows

    Any failure here should be logged explicitly.
    """
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn
    except Exception as e:
        logging.error(f"[DB] Failed to connect to {DB_PATH}: {e}", exc_info=True)
        raise
