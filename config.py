# config.py
import os

if os.name == "nt":
    DATA_ROOT = os.path.abspath(r"C:\career_ai_data")
else:
    DATA_ROOT = os.path.abspath(os.getenv("DATA_ROOT", "/app/data"))

DB_PATH = os.path.join(DATA_ROOT, "career_ai.db")
UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
GENERATED_DIR = os.path.join(DATA_ROOT, "generated_resumes")
