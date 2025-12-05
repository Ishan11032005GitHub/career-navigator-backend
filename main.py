import os, asyncio, time, logging, sqlite3
from concurrent.futures import ThreadPoolExecutor
from fastapi import (
    FastAPI, HTTPException, Depends, UploadFile, File, Request
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from dotenv import load_dotenv

# Internal modules
from models import ChatRequest, ChatResponse
from graph import career_agent, learning_agent
from auth import (
    create_token, verify_token,
    hash_password, verify_password,
    create_reset_token, verify_reset_token
)
from database import get_db
from email_utils import send_email

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

if os.name == "nt":
    miktex_path = r"C:\Program Files\MiKTeX\miktex\bin\x64"
    if miktex_path not in os.environ["PATH"]:
        os.environ["PATH"] = miktex_path + os.pathsep + os.environ["PATH"]
    print("[INFO] MiKTeX path added to PATH:", miktex_path)
else:
    print("[INFO] Running on Linux container — skipping MiKTeX PATH setup.")

# ==========================================================
# APP INIT
# ==========================================================
app = FastAPI(title="Career Navigator AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # replace with frontend domain in prod
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# DIRECTORIES
# ==========================================================
if os.name == "nt":
    DATA_ROOT = os.path.abspath(r"C:\career_ai_data")
else:
    DATA_ROOT = os.path.abspath("/app/data")

UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
GENERATED_DIR = os.path.join(DATA_ROOT, "generated_resumes")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/generated_resumes", StaticFiles(directory=GENERATED_DIR), name="generated_resumes")

print(f"📂 Serving uploads from: {UPLOAD_DIR}")
print(f"📄 Serving generated resumes from: {GENERATED_DIR}")

# ==========================================================
# EXECUTOR POOL (moved to top to avoid runtime errors)
# ==========================================================
executor = ThreadPoolExecutor(max_workers=3)

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
    if os.name == "nt":
        db_path = os.path.join(r"C:\career_ai_data", "career_ai.db")
    else:
        db_path = os.path.join("/app/data", "career_ai.db")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    db_exists = os.path.exists(db_path)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cur = conn.cursor()

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
    print(f"✅ Database ready at {db_path}" if db_exists else f"🆕 Created DB at {db_path}")


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
    response = await call_next(request)
    duration = time.time() - start
    logging.info(f"{request.method} {request.url.path} → {response.status_code} ({duration:.2f}s)")
    return response


# ==========================================================
# DEBUG ROUTES
# ==========================================================
@app.get("/debug/db-check")
async def debug_db_check():
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
        return {"database_connected": False, "error": str(e)}
    finally:
        if conn:
            conn.close()


@app.get("/test-download")
async def test_download():
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
    filename = os.path.basename(filename)
    file_path = os.path.join(GENERATED_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    if not file_path.startswith(GENERATED_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=filename,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"}
    )


# ==========================================================
# AUTH ROUTES
# ==========================================================
@app.post("/api/signup")
def signup(user: SignupRequest):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
                    (user.email, user.username, hash_password(user.password)))
        conn.commit()
        return {"msg": "Signup successful"}
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Email or username already exists")
    except Exception as e:
        conn.rollback()
        logging.error(f"[SIGNUP] error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        conn.close()


@app.post("/api/login")
def login(user: LoginRequest):
    conn = get_db()
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=?", (user.email,))
        row = cur.fetchone()
        if not row or not verify_password(user.password, row["password"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = create_token(row["username"])
        return {"token": token, "username": row["username"]}
    finally:
        conn.close()

@app.post("/api/forgot")
def forgot(req: ForgotRequest):
    email = req.email
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

    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET password=? WHERE email=?",
            (hash_password(data.new_password), email),
        )
        conn.commit()
        return {"msg": "Password updated successfully"}
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


@app.post("/api/learning", response_model=ChatResponse)
async def learning(req: ChatRequest, user=Depends(verify_token)):
    try:
        logging.info(f"[LEARNING] Request from {user}")
        loop = asyncio.get_running_loop()
        payload = req.dict()
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                lambda: learning_agent(payload, thread_id=payload.get("thread_id")),
            ),
            timeout=20.0,
        )
        # learning_agent returns {"reply": ...}, so just unpack
        return ChatResponse(**result)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="AI service timeout")
    except Exception as e:
        logging.error(f"[LEARNING ERROR] {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")



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
    return {"status": "healthy"}


@app.get("/")
def root():
    return {"status": "ok", "message": "Career Navigator AI Backend Active"}
