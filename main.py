import os, shutil
from fastapi import FastAPI, HTTPException, Depends, Form, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from models import ChatRequest, ChatResponse
from graph import career_agent, learning_agent
from auth import (
    create_token, verify_token,
    hash_password, verify_password,
    create_reset_token, verify_reset_token
)
from database import get_db
from pydantic import BaseModel, EmailStr
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import time
from fastapi import Request
import logging

# Add this to your main.py imports
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
        # Remove FileHandler for now to avoid permission issues
    ]
)

# ==========================================================
# ✅ MiKTeX PATH (only for local Windows dev, skip on Render)
# ==========================================================
if os.name == "nt":  # Windows only
    miktex_path = r"C:\Program Files\MiKTeX\miktex\bin\x64"
    if miktex_path not in os.environ["PATH"]:
        os.environ["PATH"] = miktex_path + os.pathsep + os.environ["PATH"]
    print("[INFO] MiKTeX path added to PATH:", miktex_path)
else:
    print("[INFO] Running on Linux container — skipping MiKTeX PATH setup.")

class SignupRequest(BaseModel):
    email: EmailStr
    username: str
    password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ==========================================================
# INIT
# ==========================================================
load_dotenv()

app = FastAPI(title="Career Navigator AI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================================
# STATIC FILES - CROSS-PLATFORM PATH HANDLING (WORKS LOCALLY & ON RENDER)
# ==========================================================
if os.name == "nt":  # Windows local dev
    DATA_ROOT = os.path.abspath(r"C:\career_ai_data")
else:  # Linux / Render container
    DATA_ROOT = os.path.abspath("/app/data")

UPLOAD_DIR = os.path.join(DATA_ROOT, "uploads")
GENERATED_DIR = os.path.join(DATA_ROOT, "generated_resumes")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")
app.mount("/generated_resumes", StaticFiles(directory=GENERATED_DIR), name="generated_resumes")

print(f"📂 Serving uploads from: {UPLOAD_DIR}")
print(f"📄 Serving generated resumes from: {GENERATED_DIR}")


import sqlite3
import os

# Add this function - FIXED VERSION (removed duplicate jobs table)
def init_database():
    """Initialize database with all required tables"""
    # Use the same cross-platform path as your file uploads
    if os.name == "nt":  # Windows
        DATA_ROOT = os.path.abspath(r"C:\career_ai_data")
        db_path = os.path.join(DATA_ROOT, "career_ai.db")
    else:  # Linux/Render
        DATA_ROOT = os.path.abspath("/app/data")
        db_path = os.path.join(DATA_ROOT, "career_ai.db")
    
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    db_exists = os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # -----------------------
    # USERS TABLE
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # -----------------------
    # JOBS TABLE (SINGLE VERSION - removed duplicate)
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        company TEXT NOT NULL,
        location TEXT,
        description TEXT,
        link TEXT,
        posted_by TEXT,
        posted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    # -----------------------
    # APPLICATIONS TABLE
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        resume_path TEXT NOT NULL,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    )
    """)

    # -----------------------
    # SAVED JOBS TABLE
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS saved_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        job_id INTEGER NOT NULL,
        saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, job_id),
        FOREIGN KEY (user_id) REFERENCES users(id),
        FOREIGN KEY (job_id) REFERENCES jobs(id)
    )
    """)

    # -----------------------
    # CAREER CHAT HISTORY TABLE
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS career_chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        reply TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    # -----------------------
    # LEARNING CHAT HISTORY TABLE (THE MISSING TABLE!)
    # -----------------------
    cur.execute("""
    CREATE TABLE IF NOT EXISTS learning_chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        reply TEXT NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id)
    )
    """)

    conn.commit()
    conn.close()

    if db_exists:
        print(f"📁 Using existing DB: {db_path}")
    else:
        print(f"🆕 Created new DB: {db_path}")
    print("✅ All tables created successfully!")

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logging.info(f"{request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.2f}s")
    
    return response

# Add this startup event
@app.on_event("startup")
async def startup_event():
    """Initialize database on startup"""
    print("🚀 Starting up Career Navigator AI...")
    init_database()
    print("✅ Database initialization completed")

@app.get("/debug/db-check")
async def debug_db_check():
    """Debug endpoint to check database connection"""
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Check if learning_chat_history table exists
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_chat_history'")
        table_exists = cur.fetchone() is not None
        
        # Check users table
        cur.execute("SELECT COUNT(*) as count FROM users")
        user_count = cur.fetchone()["count"]
        
        conn.close()
        
        return {
            "database_connected": True,
            "learning_chat_history_table_exists": table_exists,
            "user_count": user_count
        }
    except Exception as e:
        return {"database_connected": False, "error": str(e)}

# ==========================================================
# SINGLE PDF DOWNLOAD ENDPOINT (remove the duplicate!)
# ==========================================================
@app.get("/download-pdf/{filename}")
async def download_pdf(filename: str):
    """Serve generated PDF files with proper download headers"""
    file_path = os.path.join(GENERATED_DIR, filename)
    
    print(f"[DOWNLOAD] Requested file: {filename}")
    print(f"[DOWNLOAD] Full path: {file_path}")
    
    # Security check - ensure file is in the correct directory
    if not os.path.abspath(file_path).startswith(os.path.abspath(GENERATED_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not os.path.exists(file_path):
        print(f"[DOWNLOAD ERROR] File not found: {file_path}")
        raise HTTPException(status_code=404, detail="File not found. It may not have been generated properly.")
    
    if not filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Invalid file type")
    
    print(f"[DOWNLOAD SUCCESS] Serving file: {file_path}")
    
    # Return as file download with proper headers
    return FileResponse(
        file_path,
        media_type='application/pdf',
        filename=filename,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Access-Control-Expose-Headers': 'Content-Disposition'
        }
    )
# Add this to your main.py after the other endpoints
@app.get("/test-download")
async def test_download():
    """Test if download endpoint works by creating a test PDF"""
    import fitz
    test_filename = "test_resume.pdf"
    test_path = os.path.join(GENERATED_DIR, test_filename)
    
    # Create a simple test PDF
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

@app.post("/api/debug/learning-test")
async def debug_learning_test(test_data: dict):
    """Test the learning agent with a simple prompt"""
    try:
        # Use the same wrapper but with a known-good prompt
        simple_prompt = "Explain what Python programming is in one sentence."
        
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                executor,
                lambda: learning_agent({"message": simple_prompt}, thread_id="debug-test")
            ),
            timeout=15.0
        )
        
        return {
            "status": "success",
            "result": result,
            "agent_working": True
        }
        
    except asyncio.TimeoutError:
        return {"status": "timeout", "agent_working": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "agent_working": False}

@app.get("/api/debug/ollama-test")
async def debug_ollama_test():
    """Test Ollama connection directly"""
    import requests
    import json
    import time
    
    test_prompt = "Hello, please respond with 'OK' if you can hear me."
    
    try:
        start_time = time.time()
        
        # Test the exact same Ollama call that learning_agent uses
        response = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "gemma3:4b",
                "prompt": test_prompt,
                "stream": False
            },
            timeout=10
        )
        
        processing_time = time.time() - start_time
        
        if response.status_code == 200:
            result = response.json()
            return {
                "status": "success",
                "response": result.get("response", "No response"),
                "processing_time": f"{processing_time:.2f}s",
                "ollama_status": "connected"
            }
        else:
            return {
                "status": "http_error", 
                "status_code": response.status_code,
                "error": response.text,
                "processing_time": f"{processing_time:.2f}s",
                "ollama_status": "error"
            }
            
    except requests.exceptions.ConnectionError:
        return {
            "status": "connection_error",
            "error": "Cannot connect to Ollama at localhost:11434",
            "ollama_status": "disconnected"
        }
    except requests.exceptions.Timeout:
        return {
            "status": "timeout",
            "error": "Ollama request timed out after 10 seconds",
            "ollama_status": "timeout"
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "ollama_status": "unknown_error"
        }

# REMOVE THIS DUPLICATE ENDPOINT:
# @app.get("/generated_resumes/{filename}")
# async def download_generated_resume(filename: str):
#     """Serve generated PDF files directly"""
#     file_path = os.path.join(GENERATED_DIR, filename)
#     if not os.path.exists(file_path):
#         raise HTTPException(status_code=404, detail="File not found")
#     
#     # Return as file download with proper headers
#     return FileResponse(
#         file_path,
#         media_type='application/pdf',
#         filename=filename,
#         headers={'Content-Disposition': f'attachment; filename="{filename}"'}
#     )

# ==========================================================
# AUTH ROUTES
# ==========================================================
@app.post("/api/signup")
def signup(user: SignupRequest):
    email, username, password = user.email, user.username, user.password

    if not all([email, username, password]):
        raise HTTPException(status_code=400, detail="Missing fields")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
            (email, username, hash_password(password))
        )
        conn.commit()
        return {"msg": "Signup successful"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.post("/api/login")
def login(user: LoginRequest):
    email, password = user.email, user.password

    if not all([email, password]):
        raise HTTPException(status_code=400, detail="Missing email or password")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email=?", (email,))
    row = cur.fetchone()

    if not row or not verify_password(password, row["password"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token(row["username"])
    conn.close()
    return {"token": token, "username": row["username"]}


from email_utils import send_email

@app.post("/api/forgot")
def forgot(user: dict):
    user_email = user.get("email")
    conn = get_db()
    cur = conn.cursor()

    # Fetch the full user record
    cur.execute("SELECT username, email FROM users WHERE email=?", (user_email,))
    result = cur.fetchone()

    if not result:
        raise HTTPException(status_code=404, detail="Email not found")

    user_name, user_email = result  # unpack the tuple (name, email)

    token = create_reset_token(user_email)

    # reset_link = f"http://localhost:3000/reset?token={token}"

    body = f"""
Hi {user_name},

Here is your password reset token:

{token}

If you didn’t request a password reset, you can safely ignore this email.

– Career Navigator AI
"""
    try:
        send_email(user_email, "Career Navigator AI – Password Reset", body)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Email sending failed: {str(e)}")

    return {"msg": f"Password reset link has been sent to {user_email}"}


@app.post("/api/reset")
def reset(data: dict):
    token, new_pass = data.get("token"), data.get("new_password")
    email = verify_reset_token(token)
    if not email:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET password=? WHERE email=?", (hash_password(new_pass), email))
    conn.commit()
    conn.close()
    return {"msg": "Password updated successfully"}

# ==========================================================
# AI ROUTES
# ==========================================================
@app.post("/api/career", response_model=ChatResponse)
def career(req: ChatRequest, user=Depends(verify_token)):
    data = req.dict()
    resume_text = data.get("resume_text", "").strip()

    if not resume_text:
        raise HTTPException(status_code=400, detail="No resume text provided")

    # Run the smart agent
    result = career_agent({
        "message": data.get("message"),
        "resume_text": resume_text,
        "job_posts": data.get("job_posts", [])
    })

    # Return all available fields (reply, PDF path, LaTeX code, intent)
    return ChatResponse(
        reply=result.get("reply", ""),
        pdf_path=result.get("pdf_path"),
        latex_code=result.get("latex_code"),
        intent=result.get("intent")
    )

# Configure executor with more workers
executor = ThreadPoolExecutor(max_workers=3)  # Increased from 1 to 3

@app.post("/api/learning", response_model=ChatResponse)
async def learning(req: ChatRequest, user=Depends(verify_token)):
    """
    Optimized learning endpoint with better timeout handling and error management
    """
    try:
        logging.info(f"[LEARNING] Starting request for user: {user}")
        
        # Convert request to dict once
        request_data = req.dict()
        
        # Run the learning agent with timeout
        result = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                executor, 
                lambda: learning_agent_wrapper(request_data, req.thread_id, user)
            ),
            timeout=20.0  # Reduced from 25s to 20s for faster failover
        )
        
        logging.info(f"[LEARNING] Successfully processed request for user: {user}")
        return ChatResponse(reply=result.get("reply", ""))
        
    except asyncio.TimeoutError:
        logging.error(f"[LEARNING] Timeout for user: {user}")
        raise HTTPException(
            status_code=504, 
            detail="AI service timeout - please try again with a simpler question"
        )
    except Exception as e:
        logging.error(f"[LEARNING] Error for user {user}: {str(e)}")
        raise HTTPException(
            status_code=500, 
            detail=f"Learning service temporarily unavailable: {str(e)}"
        )

def fallback_ai_response(prompt: str) -> str:
    """Fallback to a simple rule-based response if Ollama fails"""
    prompt_lower = prompt.lower()
    
    if any(word in prompt_lower for word in ['python', 'programming']):
        return "Python is a versatile programming language great for beginners and professionals alike. It's known for its simple syntax and wide range of applications from web development to data science."
    
    elif any(word in prompt_lower for word in ['javascript', 'web']):
        return "JavaScript is essential for web development, enabling interactive websites and applications. It runs in browsers and can also be used on servers with Node.js."
    
    elif any(word in prompt_lower for word in ['learn', 'study']):
        return "I recommend starting with online tutorials, practicing regularly, and building small projects. Consistency is key to learning effectively!"
    
    else:
        return "I'd be happy to help you learn! Please ask me about specific programming languages, technologies, or learning strategies."

def learning_agent_wrapper(request_data, thread_id, user):
    """
    Wrapper function with fallback to basic responses
    """
    try:
        logging.info(f"[LEARNING_AGENT] Processing for user: {user}")
        
        # Try the actual learning agent first
        result = learning_agent(request_data, thread_id=thread_id)
        
        # If we get the technical difficulties message, use fallback
        if (result and result.get("reply") and 
            "technical difficulties" in result.get("reply", "").lower()):
            
            logging.warning(f"[LEARNING_AGENT] Using fallback for user: {user}")
            user_message = request_data.get("message", "")
            fallback_reply = fallback_ai_response(user_message)
            
            return {"reply": f"🤖 {fallback_reply}\n\n*(Note: Using basic response mode)*"}
            
        return result
        
    except Exception as e:
        logging.error(f"[LEARNING_AGENT] Critical error for user {user}: {str(e)}")
        user_message = request_data.get("message", "")
        fallback_reply = fallback_ai_response(user_message)
        
        return {
            "reply": f"🤖 {fallback_reply}\n\n*(Note: Using basic response due to technical issues)*"
        }

# ==========================================================
# JOB ROUTES
# ==========================================================
@app.post("/api/jobs/add")
def add_job(job: dict, user=Depends(verify_token)):
    title, company = job.get("title"), job.get("company")
    location = job.get("location", "")
    description = job.get("description", "")
    link = job.get("link", "")
    posted_by = user

    if not title or not company:
        raise HTTPException(status_code=400, detail="Title and company are required")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO jobs (title, company, location, description, link, posted_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, company, location, description, link, posted_by)
        )
        conn.commit()
        return {"msg": "Job added successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/jobs")
def get_jobs():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM jobs ORDER BY posted_at DESC")
    rows = cur.fetchall()
    conn.close()
    return {"jobs": [dict(r) for r in rows]}


@app.post("/api/jobs/save")
def save_job(data: dict, user=Depends(verify_token)):
    job_id = data.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="Missing job_id")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    user_row = cur.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = user_row["id"]
    try:
        cur.execute("INSERT INTO saved_jobs (user_id, job_id) VALUES (?, ?)", (user_id, job_id))
        conn.commit()
        msg = "Job saved successfully"
    except Exception as e:
        conn.rollback()
        msg = f"Job save failed: {str(e)}"
    finally:
        conn.close()

    return {"msg": msg}


@app.get("/api/jobs/saved")
def get_saved_jobs(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    user_row = cur.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = user_row["id"]

    cur.execute(
        """
        SELECT jobs.* FROM jobs
        JOIN saved_jobs ON jobs.id = saved_jobs.job_id
        WHERE saved_jobs.user_id=?
        ORDER BY saved_jobs.saved_at DESC
        """,
        (user_id,)
    )
    saved = cur.fetchall()
    conn.close()
    return {"saved_jobs": [dict(r) for r in saved]}


@app.post("/api/jobs/apply")
async def apply_to_job(
    job_id: int = Form(...),
    resume: UploadFile = File(...),
    user=Depends(verify_token)
):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    user_id = row["id"]
    filename = f"{user}_{job_id}_{resume.filename}"
    save_path = os.path.join(UPLOAD_DIR, filename)

    if resume.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid file type")

    # Stream save for speed and low memory
    with open(save_path, "wb") as f:
        shutil.copyfileobj(resume.file, f)

    try:
        cur.execute(
            "INSERT INTO applications (user_id, job_id, resume_path) VALUES (?, ?, ?)",
            (user_id, job_id, f"/uploads/{filename}")
        )
        conn.commit()
        return {"msg": "Application submitted successfully!", "resume": f"/uploads/{filename}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/jobs/applications")
def get_applications(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    user_id = row["id"]

    cur.execute(
        """
        SELECT jobs.title, jobs.company, jobs.location,
               applications.resume_path, applications.applied_at
        FROM applications
        JOIN jobs ON jobs.id = applications.job_id
        WHERE applications.user_id=?
        ORDER BY applications.applied_at DESC
        """,
        (user_id,)
    )
    apps = cur.fetchall()
    conn.close()
    return {"applications": [dict(r) for r in apps]}


@app.get("/api/jobs/received")
def get_received_applications(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT jobs.title AS job_title, jobs.company, jobs.location,
               users.username AS applicant_name, users.email AS applicant_email,
               applications.resume_path, applications.applied_at
        FROM applications
        JOIN jobs ON applications.job_id = jobs.id
        JOIN users ON applications.user_id = users.id
        WHERE jobs.posted_by=?
        ORDER BY applications.applied_at DESC
        """,
        (user,)
    )
    rows = cur.fetchall()
    conn.close()
    return {"received_applications": [dict(r) for r in rows]}

# ==========================================================
# RESUME UPLOAD
# ==========================================================
@app.post("/api/resume/upload")
async def upload_resume(resume: UploadFile = File(...), user=Depends(verify_token)):
    # --------- FAST, ROBUST UPLOAD (only change you asked for) ---------
    if not resume.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")

    import uuid
    filename = f"{user}_resume_{uuid.uuid4().hex}.pdf"
    save_path = os.path.join(UPLOAD_DIR, filename)

    try:
        # Stream to disk in chunks (prevents long waits and memory spikes)
        with open(save_path, "wb") as f:
            while True:
                chunk = await resume.read(1024 * 1024)  # 1MB
                if not chunk:
                    break
                f.write(chunk)
        return {"msg": "Resume uploaded successfully!", "path": f"/uploads/{filename}"}
    except Exception as e:
        # Ensure partial files don't linger on disk
        try:
            if os.path.exists(save_path):
                os.remove(save_path)
        except:
            pass
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")
    # -------------------------------------------------------------------

# ==========================================================
# CHAT ROUTES (Career + Learning)
# ==========================================================
@app.post("/api/career/chat/save")
def save_career_chat(chat: dict, user=Depends(verify_token)):
    message, reply = chat.get("message"), chat.get("reply")
    if not message or not reply:
        raise HTTPException(status_code=400, detail="Missing chat data")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    user_row = cur.fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        cur.execute(
            "INSERT INTO career_chat_history (user_id, message, reply) VALUES (?, ?, ?)",
            (user_row["id"], message, reply)
        )
        conn.commit()
        return {"msg": "Career chat saved successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/career/chat/history")
def get_career_chat_history(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute(
        "SELECT id, message, reply, timestamp FROM career_chat_history WHERE user_id=? ORDER BY timestamp DESC",
        (row["id"],)
    )
    chats = cur.fetchall()
    conn.close()
    return {"history": [dict(r) for r in chats]}


@app.delete("/api/career/chat/delete/{chat_id}")
def delete_career_chat(chat_id: int, user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute("DELETE FROM career_chat_history WHERE id=? AND user_id=?", (chat_id, row["id"]))
    conn.commit()
    conn.close()
    return {"msg": "Career chat deleted"}


@app.delete("/api/career/chat/clear")
def clear_career_chat_history(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute("DELETE FROM career_chat_history WHERE user_id=?", (row["id"],))
    conn.commit()
    conn.close()
    return {"msg": "All career chat history cleared"}


@app.post("/api/learning/chat/save")
def save_learning_chat(chat: dict, user=Depends(verify_token)):
    message, reply = chat.get("message"), chat.get("reply")
    
    # Better validation
    if not message or not reply:
        raise HTTPException(
            status_code=400, 
            detail="Missing chat data. Both message and reply are required."
        )
    
    if message.strip() == "" or reply.strip() == "":
        raise HTTPException(
            status_code=400, 
            detail="Message and reply cannot be empty."
        )

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM users WHERE username=?", (user,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")

        cur.execute(
            "INSERT INTO learning_chat_history (user_id, message, reply) VALUES (?, ?, ?)",
            (row["id"], message.strip(), reply.strip())
        )
        conn.commit()
        return {"msg": "Learning chat saved successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


@app.get("/api/learning/chat/history")
def get_learning_chat_history(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute(
        "SELECT id, message, reply, timestamp FROM learning_chat_history WHERE user_id=? ORDER BY timestamp DESC",
        (row["id"],)
    )
    chats = cur.fetchall()
    conn.close()
    return {"history": [dict(r) for r in chats]}


@app.delete("/api/learning/chat/delete/{chat_id}")
def delete_learning_chat(chat_id: int, user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute("DELETE FROM learning_chat_history WHERE id=? AND user_id=?", (chat_id, row["id"]))
    conn.commit()
    conn.close()
    return {"msg": "Learning chat deleted"}


@app.delete("/api/learning/chat/clear")
def clear_learning_chat_history(user=Depends(verify_token)):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute("DELETE FROM learning_chat_history WHERE user_id=?", (row["id"],))
    conn.commit()
    conn.close()
    return {"msg": "All learning chat history cleared"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}

# ==========================================================
# ROOT
# ==========================================================
@app.get("/")
def root():
    return {"status": "ok", "message": "Career Navigator AI Backend Active"}
