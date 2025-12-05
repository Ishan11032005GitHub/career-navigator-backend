import os
import asyncio
import time
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from fastapi import (
    FastAPI, HTTPException, Depends, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

# ==========================================================
# LOGGING CONFIG
# ==========================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)

# ==========================================================
# ENV + PATHS
# ==========================================================
load_dotenv()

# Base data root (single source of truth)
if os.name == "nt":
    DEFAULT_DATA_ROOT = r"C:\career_ai_data"
else:
    DEFAULT_DATA_ROOT = "/app/data"

DATA_ROOT = os.path.abspath(os.getenv("DATA_ROOT", DEFAULT_DATA_ROOT))
DB_PATH = os.path.join(DATA_ROOT, "career_ai.db")

# Ensure base data directory exists
os.makedirs(DATA_ROOT, exist_ok=True)

# MiKTeX only on Windows
if os.name == "nt":
    miktex_path = r"C:\Program Files\MiKTeX\miktex\bin\x64"
    path_env = os.environ.get("PATH", "")
    if miktex_path not in path_env:
        os.environ["PATH"] = miktex_path + os.pathsep + path_env
    print("[INFO] MiKTeX path added to PATH:", miktex_path)
else:
    print("[INFO] Running on Linux container — skipping MiKTeX PATH setup.")

# ==========================================================
# INTERNAL MODULES
# ==========================================================
try:
    from models import ChatRequest, ChatResponse
    from auth import (
        create_token, verify_token,
        hash_password, verify_password,
        create_reset_token, verify_reset_token
    )
    from database import get_db
    from email_utils import send_email
    logging.info("✅ Core modules imported successfully")
except Exception as e:
    logging.error(f"❌ Failed to import core modules: {e}", exc_info=True)
    raise

# Lazy import graph agents to prevent startup failure
_career_agent = None
_learning_agent = None


def get_career_agent():
    global _career_agent
    if _career_agent is None:
        try:
            from graph import career_agent
            _career_agent = career_agent
            logging.info("✅ Career agent imported successfully")
        except Exception as e:
            logging.error(f"❌ Failed to import career_agent: {e}", exc_info=True)
            raise
    return _career_agent


def get_learning_agent():
    global _learning_agent
    if _learning_agent is None:
        try:
            from graph import learning_agent
            _learning_agent = learning_agent
            logging.info("✅ Learning agent imported successfully")
        except Exception as e:
            logging.error(f"❌ Failed to import learning_agent: {e}", exc_info=True)
            raise
    return _learning_agent


# ==========================================================
# APP INIT
# ==========================================================
app = FastAPI(title="Career Navigator AI")

# CORS: allow GitHub Pages + localhost by default, override via env
default_origins = [
    "https://ishan11032005github.github.io",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
env_origins = os.getenv("FRONTEND_ORIGINS")
if env_origins:
    allow_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
else:
    allow_origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,          # allow Authorization header + cookies if needed
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# DIRECTORIES
# ==========================================================
UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
GENERATED_DIR = os.path.join(DATA_ROOT, "generated_resumes")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/generated_resumes", StaticFiles(directory=GENERATED_DIR), name="generated_resumes")

print(f"📂 Serving uploads from: {UPLOAD_DIR}")
print(f"📄 Serving generated resumes from: {GENERATED_DIR}")
print(f"🗄️ Using database at: {DB_PATH}")

# ==========================================================
# EXECUTOR POOL
# ==========================================================
# Increase workers a bit for concurrent /api/learning usage
executor = ThreadPoolExecutor(max_workers=10)

# ==========================================================
# MODELS
# ==========================================================
class SignupRequest(BaseModel):
    email: EmailStr
    username: str
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ForgotRequest(BaseModel):
    email: EmailStr


class ResetRequest(BaseModel):
    token: str
    new_password: str


# ==========================================================
# DATABASE INITIALIZATION
# ==========================================================
def init_database():
    """
    Single source of truth DB init using DB_PATH.
    Also enables WAL and foreign keys for better robustness.
    """
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db_exists = os.path.exists(DB_PATH)

    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
    cur = conn.cursor()

    # Basic tuning for concurrency + integrity
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA foreign_keys=ON;")

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT,
        description TEXT,
        link TEXT,
        posted_by TEXT,
        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        resume_path TEXT NOT NULL,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    );

    CREATE TABLE IF NOT EXISTS saved_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, job_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    );

    CREATE TABLE IF NOT EXISTS career_chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        reply TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS learning_chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        reply TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    );
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database ready at {DB_PATH}" if db_exists else f"🆕 Created DB at {DB_PATH}")


@app.on_event("startup")
async def startup_event():
    print("🚀 Starting up Career Navigator AI...")
    init_database()
    print("✅ Database initialization completed")


# ==========================================================
# MIDDLEWARE
# ==========================================================
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    try:
        response = await call_next(request)
    except Exception as e:
        logging.error(f"[UNHANDLED ERROR] {request.method} {request.url.path}: {e}", exc_info=True)
        raise
    duration = time.time() - start
    logging.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.2f}s)")
    return response


# ==========================================================
# DEBUG HELPER
# ==========================================================
def assert_debug_enabled():
    """
    Protects debug endpoints from being exposed in production.
    Set DEBUG_ROUTES_ENABLED=true in env to use them.
    """
    if os.getenv("DEBUG_ROUTES_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Not found")


# ==========================================================
# DEBUG ROUTES
# ==========================================================
@app.get("/debug/db-check")
async def debug_db_check():
    assert_debug_enabled()
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE name='learning_chat_history'")
        table_exists = cur.fetchone() is not None
        cur.execute("SELECT COUNT(*) FROM users")
        user_count = cur.fetchone()[0]
        return {
            "database_connected": True,
            "learning_chat_history_exists": table_exists,
            "user_count": user_count,
        }
    except Exception as e:
        logging.error(f"[DEBUG DB CHECK] error: {e}", exc_info=True)
        return {"database_connected": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


@app.get("/test-download")
async def test_download():
    assert_debug_enabled()
    import fitz
    test_filename = "test_resume.pdf"
    test_path = os.path.join(GENERATED_DIR, test_filename)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "TEST RESUME - Career Navigator AI")
    page.insert_text((50, 70), "This is a test PDF to verify download functionality")
    doc.save(test_path)
    doc.close()
    return {
        "message": "Test PDF created",
        "preview_url": f"/generated_resumes/{test_filename}",
        "download_url": f"/download-pdf/{test_filename}"
    }


# ==========================================================
# FILE DOWNLOAD
# ==========================================================
@app.get("/download-pdf/{filename}")
async def download_pdf(filename: str):
    safe_name = os.path.basename(filename)
    file_path = os.path.join(GENERATED_DIR, safe_name)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=safe_name,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"}
    )


# ==========================================================
# AUTH ROUTES
# ==========================================================
@app.post("/api/signup")
def signup(user: SignupRequest):
    email = user.email.strip().lower()
    username = user.username.strip()
    password = user.password

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
            (email, username, hash_password(password)),
        )
        conn.commit()
        return {"msg": "Signup successful"}
    except sqlite3.IntegrityError as e:
        conn.rollback()
        logging.warning(f"[SIGNUP] Integrity error: {e}")
        # Could be email or username; don't leak which one
        raise HTTPException(status_code=409, detail="Email or username already exists")
    except Exception as e:
        conn.rollback()
        logging.error(f"[SIGNUP] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/api/login")
def login(user: LoginRequest):
    email = user.email.strip().lower()
    password = user.password

    if not password:
        raise HTTPException(status_code=400, detail="Password is required")

    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (email,))
        row = cur.fetchone()
        if not row or not verify_password(password, row["password"]):
            # Don't leak which part is wrong
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_token(row["username"])
        return {"token": token, "username": row["username"]}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[LOGIN] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/api/forgot")
def forgot(req: ForgotRequest):
    email = req.email.strip().lower()
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT username, email FROM users WHERE email=?", (email,))
        result = cur.fetchone()

        # Always respond 200; only send email if user exists
        if result:
            username, user_email = result["username"], result["email"]
            token = create_reset_token(user_email)
            body = (
                f"Hi {username},\n\n"
                f"Here is your password reset token:\n{token}\n\n"
                f"– Career Navigator AI"
            )
            send_email(user_email, "Career Navigator AI – Password Reset", body)

        return {"msg": "If the email exists, a reset link has been sent."}
    except Exception as e:
        logging.error(f"[FORGOT] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/api/reset")
def reset(data: ResetRequest):
    email = verify_reset_token(data.token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    new_password = data.new_password
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET password=? WHERE email=?",
            (hash_password(new_password), email.strip().lower()),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="User not found")
        conn.commit()
        return {"msg": "Password updated successfully"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        logging.error(f"[RESET] error: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ==========================================================
# AI ROUTES
# ==========================================================
@app.post("/api/career", response_model=ChatResponse)
def career(req: ChatRequest, user=Depends(verify_token)):
    try:
        career_agent = get_career_agent()
        data = req.dict()
        resume_text = data.get("resume_text", "").strip()
        if not resume_text:
            raise HTTPException(status_code=400, detail="No resume text provided")
        result = career_agent({
            "message": data.get("message"),
            "resume_text": resume_text,
            "job_posts": data.get("job_posts", [])
        })
        return ChatResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[CAREER] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Career agent error")


@app.post("/api/learning", response_model=ChatResponse)
async def learning(req: ChatRequest, user=Depends(verify_token)):
    try:
        logging.info(f"[LEARNING] Request from {user}")
        learning_agent = get_learning_agent()
        loop = asyncio.get_running_loop()
        payload = req.dict()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                lambda: learning_agent(payload, thread_id=payload.get("thread_id")),
            ),
            timeout=60.0,  # more realistic timeout for heavy calls
        )
        return ChatResponse(**result)
    except asyncio.TimeoutError:
        logging.error("[LEARNING] Timeout")
        raise HTTPException(status_code=504, detail="AI service timeout")
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"[LEARNING ERROR] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Learning agent error")


# ==========================================================
# CHAT HISTORY ROUTES
# ==========================================================
@app.post("/api/learning/chat/save")
def save_learning_chat(chat: dict, user=Depends(verify_token)):
    message, reply = chat.get("message", "").strip(), chat.get("reply", "").strip()
    if not message or not reply:
        raise HTTPException(status_code=400, detail="Message and reply required")

    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=?", (user,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        cur.execute(
            "INSERT INTO learning_chat_history (user_id, message, reply) VALUES (?, ?, ?)",
            (row["id"], message, reply),
        )
        conn.commit()
        return {"msg": "Learning chat saved successfully"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        logging.error(f"[SAVE CHAT] error: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.get("/api/learning/chat/history")
def get_learning_chat_history(user=Depends(verify_token)):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=?", (user,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        cur.execute(
            "SELECT id, message, reply, timestamp "
            "FROM learning_chat_history WHERE user_id=? ORDER BY timestamp DESC",
            (row["id"],),
        )
        data = cur.fetchall()
        return {"history": [dict(r) for r in data]}
    except Exception as e:
        logging.error(f"[GET CHAT HISTORY] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.delete("/api/learning/chat/clear")
def clear_learning_chat_history(user=Depends(verify_token)):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username=?", (user,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        cur.execute("DELETE FROM learning_chat_history WHERE user_id=?", (row["id"],))
        conn.commit()
        return {"msg": "All learning chat history cleared"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        logging.error(f"[CLEAR CHAT] error: {e}", exc_info=True)
        conn.rollback()
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


# ==========================================================
# HEALTH & ROOT
# ==========================================================
@app.get("/health")
def health_check():
    """Basic health check - returns quickly if app is running"""
    return {"status": "healthy", "message": "API is running"}


@app.get("/health/detailed")
def detailed_health_check():
    """Comprehensive health check including all imports and database"""
    status = {
        "status": "healthy",
        "database": "error",
        "career_agent": "error",
        "learning_agent": "error"
    }

    # Check database
    try:
        conn = get_db()
        conn.close()
        status["database"] = "ok"
    except Exception as e:
        logging.error(f"Database check failed: {e}")
        status["database"] = str(e)

    # Check career agent import
    try:
        get_career_agent()
        status["career_agent"] = "ok"
    except Exception as e:
        logging.error(f"Career agent check failed: {e}")
        status["career_agent"] = str(e)

    # Check learning agent import
    try:
        get_learning_agent()
        status["learning_agent"] = "ok"
    except Exception as e:
        logging.error(f"Learning agent check failed: {e}")
        status["learning_agent"] = str(e)

    all_ok = all(
        status[key] == "ok"
        for key in ("database", "career_agent", "learning_agent")
    )
    if not all_ok:
        status["status"] = "degraded"

    return status


@app.get("/")
def root():
    return {"status": "ok", "message": "Career Navigator AI Backend Active"}
