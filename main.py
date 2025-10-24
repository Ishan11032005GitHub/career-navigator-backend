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

origins = [
    "https://ishan11032005github.github.io",
    "https://career-navigator-ai-1.onrender.com",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,       # Only allow your actual frontends
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


@app.post("/api/learning", response_model=ChatResponse)
def learning(req: ChatRequest, user=Depends(verify_token)):
    result = learning_agent(req.dict(), thread_id=req.thread_id)
    return ChatResponse(reply=result.get("reply", ""))

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
    if not message or not reply:
        raise HTTPException(status_code=400, detail="Missing chat data")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username=?", (user,))
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    cur.execute(
        "INSERT INTO learning_chat_history (user_id, message, reply) VALUES (?, ?, ?)",
        (row["id"], message, reply)
    )
    conn.commit()
    conn.close()
    return {"msg": "Learning chat saved successfully"}


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
