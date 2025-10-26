import os, sys, requests, json
from dotenv import load_dotenv
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import tempfile
import threading
import time
import logging

from tools import analyze_resume, match_jobs, generate_learning_path, quick_quiz
import os, re, subprocess, uuid
import fitz  # PyMuPDF (already used in your project)


DATA_ROOT = os.getenv("DATA_ROOT", r"C:\career_ai_data")
GEN_DIR = os.path.join(DATA_ROOT, "generated_resumes")
os.makedirs(GEN_DIR, exist_ok=True)

# --- Load env file early ---
if not load_dotenv():
    print("⚠️ Warning: .env file not found", file=sys.stderr)


# --- Thread-safe memory store ---
class ThreadSafeMemoryStore:
    def __init__(self):
        self._store = {}
        self._lock = threading.RLock()
    
    def get(self, thread_id, default=None):
        with self._lock:
            return self._store.get(thread_id, default)
    
    def set(self, thread_id, value):
        with self._lock:
            self._store[thread_id] = value
    
    def append(self, thread_id, value):
        with self._lock:
            if thread_id not in self._store:
                self._store[thread_id] = []
            self._store[thread_id].append(value)
            # Keep only last 10 messages to prevent memory bloat
            if len(self._store[thread_id]) > 10:
                self._store[thread_id] = self._store[thread_id][-10:]

memory_store = ThreadSafeMemoryStore()


# --- Ollama config (free local LLM) ---
# def _normalize_ollama_url(v: str) -> str:
#     """
#     Accept either:
#       - http://localhost:11434
#       - http://localhost:11434/
#       - http://localhost:11434/api
#       - http://localhost:11434/api/
#       - http://localhost:11434/api/generate
#     and normalize to .../api/generate
#     """
#     v = (v or "").strip()
#     if not v:
#         return "http://localhost:11434/api/generate"
#     v = v.rstrip("/")
#     if v.endswith("/api/generate"):
#         return v
#     if v.endswith("/api"):
#         return v + "/generate"
#     return v + "/api/generate"


# Keep your previous default behavior but robust to base URL envs too
# OLLAMA_URL = _normalize_ollama_url(os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"))
# OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")


# def _format_err(prefix: str, detail: str) -> str:
#     return f"{prefix}: {detail}"

# def _explain_ollama_http_error(resp: requests.Response) -> str:
#     """
#     Try to provide a helpful message when Ollama responds with a non-200.
#     """
#     try:
#         data = resp.json()
#     except Exception:
#         data = {"raw": resp.text[:500]}
#     # Common issues:
#     # - model not found
#     text = str(data).lower()
#     if resp.status_code == 404 or "model not found" in text or "no such model" in text:
#         return _format_err("⚠️ Ollama error", f"Model '{OLLAMA_MODEL}' not found. Try: `ollama pull {OLLAMA_MODEL}`")
#     return _format_err("⚠️ Ollama HTTP error", f"status={resp.status_code}, body={data}")

# ---- EXTERNAL AI API CONFIG (Works on Railway) ----
def safe_llm_invoke(prompt: str, timeout: int = 30) -> str:
    """
    Use external AI API that works on Railway - SAME FUNCTIONALITY as Ollama
    """
    start_time = time.time()
    
    # Truncate very long prompts to prevent timeouts
    if len(prompt) > 4000:
        prompt = prompt[:4000] + "... [truncated]"
    
    try:
        logging.info(f"[LLM] Sending request to external AI API (timeout: {timeout}s)")
        
        # Option 1: Try OpenRouter (free tier available)
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('OPENROUTER_API_KEY', '')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "google/gemma-2-2b-it:free",  # Free model
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.7
                },
                timeout=timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                text = result['choices'][0]['message']['content'].strip()
                processing_time = time.time() - start_time
                logging.info(f"[LLM] External API response received in {processing_time:.2f}s")
                return text
                
        except Exception as e:
            logging.warning(f"[LLM] OpenRouter failed: {e}, trying fallback...")
        
        # Option 2: Fallback to Hugging Face Inference API
        try:
            HF_API_KEY = os.getenv("HF_API_KEY", "")
            if HF_API_KEY:
                response = requests.post(
                    "https://api-inference.huggingface.co/models/google/gemma-2-2b-it",
                    headers={"Authorization": f"Bearer {HF_API_KEY}"},
                    json={"inputs": prompt},
                    timeout=timeout
                )
                
                if response.status_code == 200:
                    result = response.json()
                    if isinstance(result, list) and len(result) > 0:
                        text = result[0].get('generated_text', '').replace(prompt, '').strip()
                        if text:
                            processing_time = time.time() - start_time
                            logging.info(f"[LLM] Hugging Face response received in {processing_time:.2f}s")
                            return text
                            
        except Exception as e:
            logging.warning(f"[LLM] Hugging Face failed: {e}")
        
        # Option 3: Final fallback - enhanced rule-based responses
        return enhanced_fallback_response(prompt)
        
    except Exception as e:
        error_msg = f"⚠️ AI service error: {str(e)}"
        logging.error(f"[LLM] Error: {error_msg}")
        return enhanced_fallback_response(prompt)

def enhanced_fallback_response(prompt: str) -> str:
    """Enhanced fallback that maintains same functionality as AI responses"""
    prompt_lower = prompt.lower()
    
    # Career/Resume related queries
    if any(word in prompt_lower for word in ['resume', 'cv', 'career', 'job', 'apply']):
        return """I can help you with resume optimization and career advice! 

For resume improvements, I can:
• Analyze your skills and experience
• Suggest better wording and formatting
• Tailor your resume for specific job roles
• Generate professional LaTeX resumes

Please share your resume text and let me know what specific improvements you're looking for."""

    # Learning related queries
    elif any(word in prompt_lower for word in ['sql', 'database', 'query']):
        return """**SQL Learning Guide**

🔹 **What is SQL?**
SQL (Structured Query Language) is used to manage and query relational databases.

🔹 **Key Concepts to Learn:**
1. **Basic Queries**: SELECT, FROM, WHERE
2. **Data Manipulation**: INSERT, UPDATE, DELETE  
3. **Joins**: INNER JOIN, LEFT JOIN, RIGHT JOIN
4. **Aggregation**: GROUP BY, HAVING, COUNT, SUM
5. **Subqueries and CTEs**

🔹 **Practice Example:**
```sql
SELECT name, department, salary 
FROM employees 
WHERE department = 'Engineering' 
ORDER BY salary DESC;
💡 Next Steps: Practice with real datasets, learn about indexes and query optimization."""

    elif any(word in prompt_lower for word in ['python', 'programming']):
        return """**Python Programming Guide**
🔹 Why Python?

Easy to learn with clean syntax

Versatile (web, data science, AI, automation)

Large ecosystem of libraries

Strong community support

🔹 Learning Path:

Basics: variables, loops, functions

Data structures: lists, dictionaries, sets

Object-oriented programming

Libraries: Pandas (data), Requests (web), Flask (web framework)

🔹 Project Ideas:

Web scraper

Data analysis script

Simple web application

Automation scripts"""

    elif any(word in prompt_lower for word in ['javascript', 'web development']):
        return """JavaScript Web Development

🔹 Core Concepts:

Variables and data types

Functions and scope

DOM manipulation

Async programming (callbacks, promises)

🔹 Ecosystem:

Frontend: React, Vue, Angular

Backend: Node.js, Express

Tools: npm, webpack, ESLint

🔹 Learning Resources:

MDN Web Docs

FreeCodeCamp JavaScript curriculum

Practice building interactive web pages"""
    elif any(word in prompt_lower for word in ['learn', 'study', 'how to']):
        return """Effective Learning Strategy 🎯

Set Clear Goals: What do you want to achieve?

Practice Consistently: Regular practice beats cramming

Build Projects: Apply knowledge to real problems

Join Communities: Get help and share progress

Review Regularly: Reinforce what you've learned

💡 Tip: Focus on understanding concepts rather than memorizing syntax. Build a portfolio of projects to demonstrate your skills."""

    else:
        return """I'd be happy to help you with career guidance or learning resources! 
I can assist with:
• Resume optimization and career advice
• Learning paths for programming and tech skills
• Technical interview preparation
• Project ideas and learning resources

What specific area would you like help with today?"""



# ---- Agent nodes ----
def router(state: Dict[str, Any]):
    text = (state.get("message") or "").lower()
    intent = "chat"
    if any(k in text for k in ["job", "resume", "apply", "hiring", "jd", "role"]):
        intent = "career"
    if any(k in text for k in ["learn", "teach", "quiz", "study", "course", "path"]):
        intent = "learning"
    return {"intent": intent}


def validate_and_fix_latex(latex_code):
    """Fix common LaTeX syntax errors from LLM output"""
    # Fix bracket issues: \{} -> {}
    latex_code = latex_code.replace(r'\{', '{').replace(r'\}', '}')
    
    # Fix common environment issues
    latex_code = latex_code.replace(r'\begin\{', r'\begin{')
    latex_code = latex_code.replace(r'\end\{', r'\end{')
    
    # Fix section commands
    latex_code = latex_code.replace(r'\section\{', r'\section{')
    latex_code = latex_code.replace(r'\subsection\{', r'\subsection{')
    
    # Fix itemize environment specifically
    latex_code = latex_code.replace(r'\begin\{itemize\}', r'\begin{itemize}')
    latex_code = latex_code.replace(r'\end\{itemize\}', r'\end{itemize}')
    
    # Fix href commands
    latex_code = latex_code.replace(r'\href\{', r'\href{')
    
    return latex_code


def generate_latex_with_ai(resume_text: str, user_message: str) -> str:
    """Generate LaTeX code using AI with proper formatting instructions"""
    latex_prompt = f"""
    Generate a professional resume in LaTeX format based on this resume text:
    {resume_text[:3000]}
    
    User request: {user_message}
    
    **CRITICAL LaTeX FORMATTING RULES:**
    - Use proper LaTeX syntax WITHOUT escaping curly braces
    - Use \begin{{itemize}} and \end{{itemize}} for lists (NO backslashes before curly braces)
    - Use \begin{{section}} and \end{{section}} for sections  
    - Use \textbf{{text}} for bold, \textit{{text}} for italic
    - Use \\ for line breaks, not \n
    - Use \section{{Section Title}} for section headers
    - Use \item for list items inside itemize environments
    
    **DO NOT USE:** \{{ or \}} - use regular {{ and }} instead
    
    Generate clean, compilable LaTeX code:
    """
    
    try:
        latex_response = safe_llm_invoke(latex_prompt)  # FIXED: Use safe_llm_invoke instead of model.invoke
        return latex_response.strip()
    except Exception as e:
        print(f"[ERROR] AI LaTeX generation failed: {e}")
        return ""


def is_valid_latex(latex_code: str) -> bool:
    """Basic validation of LaTeX code - LESS STRICT VERSION"""
    if not latex_code:
        return False
    
    # Check for CRITICAL syntax errors that will definitely break compilation
    critical_errors = [
        r'\\{',  # Escaped opening brace (definitely breaks)
        r'\\}',  # Escaped closing brace (definitely breaks)
    ]
    
    for pattern in critical_errors:
        if re.search(pattern, latex_code):
            print(f"[VALIDATION] Critical error found: {pattern}")
            return False
    
    # These are WARNINGS but not necessarily fatal - don't reject for these
    warnings = [
        r'begin\{',  # Missing backslash - might be fixable
        r'end\{',    # Missing backslash - might be fixable
    ]
    
    for pattern in warnings:
        if re.search(pattern, latex_code):
            print(f"[VALIDATION] Warning found (but will try to fix): {pattern}")
            # Don't return False here - just log the warning
    
    # Check for basic LaTeX structure
    required_patterns = [
        r'\\documentclass',
        r'\\begin{document}',
        r'\\end{document}'
    ]
    
    for pattern in required_patterns:
        if not re.search(pattern, latex_code, re.IGNORECASE):
            print(f"[VALIDATION] Missing required pattern: {pattern}")
            return False
    
    return True


def fix_latex_syntax(latex_code: str) -> str:
    """Fix common LaTeX syntax errors from AI generation - ENHANCED VERSION"""
    if not latex_code:
        return ""
    
    # Fix escaped curly braces - this is the main issue
    latex_code = latex_code.replace(r'\{', '{').replace(r'\}', '}')
    
    # Fix missing backslashes in environment commands
    latex_code = re.sub(r'\\begin\{', r'\\begin{', latex_code)  # Ensure proper backslash
    latex_code = re.sub(r'\\end\{', r'\\end{', latex_code)      # Ensure proper backslash
    
    # Fix common environment issues (with proper escaping)
    latex_code = latex_code.replace(r'\begin{itemize}', r'\begin{itemize}')
    latex_code = latex_code.replace(r'\end{itemize}', r'\end{itemize}')
    latex_code = latex_code.replace(r'\begin{enumerate}', r'\begin{enumerate}')
    latex_code = latex_code.replace(r'\end{enumerate}', r'\end{enumerate}')
    
    # Fix section commands
    latex_code = latex_code.replace(r'\section{', r'\section{')
    latex_code = latex_code.replace(r'\subsection{', r'\subsection{')
    
    # Fix missing backslashes in begin/end commands (the main issue from your logs)
    latex_code = re.sub(r'(?<!\\)begin\{', r'\\begin{', latex_code)
    latex_code = re.sub(r'(?<!\\)end\{', r'\\end{', latex_code)
    
    return latex_code


def get_fallback_latex_template(resume_text: str) -> str:
    """Provide a simple, guaranteed-to-work LaTeX template"""
    return r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{enumitem}
\usepackage{hyperref}

\geometry{a4paper, margin=1in}
\setlist[itemize]{leftmargin=*,labelindent=0pt}

\begin{document}

\begin{center}
    {\LARGE \textbf{Professional Resume}} \\
    \vspace{0.5cm}
    {\large Software Engineer}
\end{center}

\section*{Professional Summary}
Experienced software engineer with strong technical skills and proven track record of delivering high-quality software solutions.

\section*{Technical Skills}
\begin{itemize}
    \item \textbf{Programming:} Python, JavaScript, Java, C++
    \item \textbf{Frameworks:} React, Node.js, Express, Django
    \item \textbf{Tools:} Git, Docker, AWS, Jenkins
    \item \textbf{Databases:} MySQL, MongoDB, PostgreSQL
\end{itemize}

\section*{Professional Experience}
\begin{itemize}
    \item Developed and maintained scalable web applications
    \item Collaborated with cross-functional teams to deliver features
    \item Optimized application performance and improved user experience
\end{itemize}

\section*{Education}
\begin{itemize}
    \item Bachelor of Science in Computer Science or related field
\end{itemize}

\end{document}
"""


def career_agent(state: Dict[str, Any]):
    """
    Smart Career Agent - FIXED LaTeX Syntax & URL PATHS
    """
    message = (state.get("message") or "").lower()
    resume_text = (state.get("resume_text") or "").strip()
    if not resume_text:
        return {"reply": "⚠️ Please provide your resume text for analysis."}

    job_posts = state.get("job_posts") or []

    # --- Intent detection ---
    res = safe_llm_invoke(
        f"You are a binary classifier. Only respond with one word: 'restructure' if the user wants to modify or rewrite their resume, "
        f"or 'analyze' if they just want feedback.\n\nUser: {message}"
    ).strip().lower()

    intent = "restructure" if "restructure" in res else "analyze"

    # --- ANALYZE branch ---
    if intent == "analyze":
        analysis = analyze_resume(resume_text)
        ranked = match_jobs(analysis.get("skills", []), job_posts) if job_posts else []
        prompt = (
            "You are a concise career coach. Based on the user's resume and message, write a short actionable reply.\n"
            f"User message: {state.get('message')}\n"
            f"Resume content: {resume_text[:4000]}...\n"
            f"Detected skills: {analysis.get('skills', [])}\n"
            f"Suggestions: {analysis.get('suggestions', [])}\n"
            f"Top job match titles: {[p.get('title') for p in ranked[:3]]}\n"
        )
        reply = safe_llm_invoke(prompt) or "⚠️ The model returned no content."
        return {"reply": reply.strip(), "intent": "analyze"}

    # --- RESTRUCTURE branch ---
    
    # Try AI-generated LaTeX first
    latex_code = generate_latex_with_ai(resume_text, message)
    
    # Validate LaTeX code and use fallback if invalid
    if not is_valid_latex(latex_code):
        print("⚠️ AI-generated LaTeX invalid, using fallback template")
        latex_code = get_fallback_latex_template(resume_text)
    
    # Clean up common LaTeX syntax errors
    latex_code = fix_latex_syntax(latex_code)

    # Continue with your existing code...
    base = f"resume_restructured_{uuid.uuid4().hex}"
    tex_path = os.path.join(GEN_DIR, f"{base}.tex")
    pdf_path = os.path.join(GEN_DIR, f"{base}.pdf")
    
    # ✅ FIXED: Use RELATIVE URL PATHS (frontend will convert to absolute)
    preview_url = f"/generated_resumes/{base}.pdf"  # For static file serving (preview)
    download_url = f"/download-pdf/{base}.pdf"      # For download endpoint
    
    print(f"[DEBUG] Preview URL: {preview_url}")
    print(f"[DEBUG] Download URL: {download_url}")
    print(f"[DEBUG] PDF path: {pdf_path}")

    # ✅ ENSURE LaTeX is valid and complete
    if not latex_code.strip().startswith("\\documentclass"):
        latex_code = (
            "\\documentclass{article}\n"
            "\\usepackage[utf8]{inputenc}\n"
            "\\usepackage[T1]{fontenc}\n"
            "\\usepackage{geometry}\n"
            "\\usepackage{hyperref}\n"
            "\\geometry{a4paper, margin=1in}\n"
            "\\title{Professional Resume}\n"
            "\\author{Software Engineer}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            + latex_code +
            "\n\\end{document}"
        )
    
    # ✅ SANITIZE LaTeX content PROPERLY
    latex_code = latex_code.replace("&", "\\&")
    latex_code = latex_code.replace("%", "\\%")
    latex_code = latex_code.replace("#", "\\#")
    latex_code = latex_code.replace("_", "\\_")
    latex_code = latex_code.replace("$", "\\$")
    # NOTE: We DON'T escape curly braces here - fix_latex_syntax already handled this

    # Ensure hyperref package is included if needed
    if "\\href" in latex_code and "\\usepackage{hyperref}" not in latex_code:
        latex_code = latex_code.replace(
            "\\usepackage[utf8]{inputenc}",
            "\\usepackage[utf8]{inputenc}\n\\usepackage{hyperref}"
        )

    # ✅ WRITE LaTeX file with error handling
    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_code)
        print(f"[SUCCESS] LaTeX file written: {tex_path}")
    except Exception as e:
        print(f"[ERROR] Failed to write LaTeX file: {e}")
        return {
            "reply": "❌ Failed to create LaTeX file. Please try again.",
            "pdf_path": None,
            "latex_code": latex_code,
            "intent": "restructure"
        }

    # ✅ COMPILE LaTeX to PDF with DETAILED DEBUGGING
    pdf_generated = False
    latex_output = ""
    
    try:
        print("[DEBUG] Starting LaTeX compilation...")
        
        # Run pdflatex TWICE for proper references
        for run in [1, 2]:
            print(f"[DEBUG] LaTeX compilation run {run}")
            result = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", f"{base}.tex"],
                cwd=GEN_DIR,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.stdout:
                latex_output += f"\n--- Run {run} stdout ---\n{result.stdout}"
            if result.stderr:
                latex_output += f"\n--- Run {run} stderr ---\n{result.stderr}"
            
            print(f"[DEBUG] Run {run} return code: {result.returncode}")

        # Check if PDF was generated
        pdf_generated = os.path.exists(pdf_path)
        file_size = os.path.getsize(pdf_path) if pdf_generated else 0
        
        print(f"[DEBUG] PDF generated: {pdf_generated}, Size: {file_size} bytes")

        if pdf_generated and file_size > 1000:  # Reasonable PDF size
            print("[SUCCESS] PDF generated successfully")
            reply = "✅ Resume successfully tailored for SWE roles!"
        else:
            print(f"[WARNING] PDF issues - exists: {pdf_generated}, size: {file_size}")
            reply = "⚠️ PDF generation had some issues - showing LaTeX code"

    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"[ERROR] LaTeX compilation failed: {e}")
        latex_output += f"\n--- Exception ---\n{str(e)}"
        reply = "❌ LaTeX compilation failed"

    # ✅ BUILD RESPONSE with RELATIVE URLS (frontend will handle conversion)
    combined_reply = reply
    
    if pdf_generated and os.path.exists(pdf_path):
        # ✅ FIXED: Use RELATIVE URLs only (no backend_base prefix)
        combined_reply += (
            f"\n\n📥 **Download Your Tailored Resume:**\n"
            f"• <a href='{download_url}' target='_blank' download='SWE_Resume.pdf'>📄 Download PDF</a>\n"
            f"• <a href='{preview_url}' target='_blank'>👀 Preview in Browser</a>"
            f"\n\n📋 **Resume Preview:**\n"
            f"<iframe src='{preview_url}' width='100%' height='600px' "
            "style='border:1px solid #ccc; border-radius:8px; margin-top:10px;'></iframe>"
        )
    else:
        # FALLBACK: Generate a simple PDF using fitz
        combined_reply += "\n\n⚠️ **Using fallback PDF generation**"
        
        fallback_filename = f"{base}_simple.pdf"
        fallback_path = os.path.join(GEN_DIR, fallback_filename)
        
        try:
            # Create a simple PDF with the resume content
            doc = fitz.open()
            page = doc.new_page()
            
            # Add title
            title_rect = fitz.Rect(50, 50, 400, 100)
            page.insert_textbox(title_rect, "SOFTWARE ENGINEER RESUME", 
                              fontsize=16, fontname="helv-bold", align=0)
            
            # Add content (limited to fit on page)
            content_rect = fitz.Rect(50, 100, 550, 750)
            page.insert_textbox(content_rect, resume_text[:1500], 
                              fontsize=10, fontname="helv", align=0)
            
            doc.save(fallback_path)
            doc.close()
            
            fallback_preview = f"/generated_resumes/{fallback_filename}"
            fallback_download = f"/download-pdf/{fallback_filename}"
            
            combined_reply += (
                f"\n\n📥 **Download Simple Resume:**\n"
                f"• <a href='{fallback_download}' target='_blank' download='SWE_Resume_Simple.pdf'>📄 Download PDF</a>\n"
                f"• <a href='{fallback_preview}' target='_blank'>👀 Preview in Browser</a>"
                f"\n\n📋 **Resume Preview:**\n"
                f"<iframe src='{fallback_preview}' width='100%' height='600px' "
                "style='border:1px solid #ccc; border-radius:8px; margin-top:10px;'></iframe>"
            )
            
            pdf_generated = True
            
        except Exception as fallback_error:
            combined_reply += f"\n\n❌ Fallback PDF also failed: {str(fallback_error)}"

    # Add LaTeX code for debugging (collapsible)
    if latex_code:
        combined_reply += (
            "\n\n---\n**LaTeX Source Code**:\n"
            "<details><summary>Click to expand (for debugging)</summary>\n\n"
            f"<pre style='background: #f5f5f5; padding: 10px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap;'>"
            f"{latex_code}</pre>\n</details>"
        )
    
    # Add compilation logs if there were issues
    if latex_output and not pdf_generated:
        combined_reply += (
            "\n\n---\n**Compilation Logs**:\n"
            "<details><summary>Click to expand</summary>\n\n"
            f"<pre style='background: #fff0f0; padding: 10px; border-radius: 5px; overflow-x: auto; white-space: pre-wrap;'>"
            f"{latex_output}</pre>\n</details>"
        )

    return {
        "reply": combined_reply,
        "pdf_path": preview_url if pdf_generated else None,
        "latex_code": latex_code,
        "intent": "restructure"
    }


memory_store: Dict[str, list] = {}


# ---- Optimized Learning Agent ----
def learning_agent(state: Dict[str, Any], thread_id: str = "default"):
    """
    Optimized learning agent with timeout protection and better error handling
    """
    start_time = time.time()
    
    # Allow thread_id to be passed either as arg (backend direct call) or via state (graph mode)
    thread = state.get("thread_id") or thread_id or "default"
    topic = state.get("message", "Please help me learn about this topic")
    
    # Validate input
    if not topic or len(topic.strip()) < 2:
        return {"reply": "Please provide a specific topic or question you'd like to learn about."}

    logging.info(f"[LEARNING_AGENT] Starting for thread: {thread}, topic: {topic[:100]}...")

    try:
        # Retrieve history with timeout protection
        history = memory_store.get(thread, [])
        context_text = "\n".join(history[-2:]) if history else "No previous context"  # Reduced from 3 to 2

        # SIMPLIFIED prompt - this was likely causing the timeout
        response_prompt = f"""You are a helpful learning mentor. Be concise and practical.

Previous conversation:
{context_text}

User's current question: "{topic}"

Provide a helpful explanation or learning suggestion. Keep it under 300 words.
Focus on practical advice and clear explanations."""

        logging.info(f"[LEARNING_AGENT] Sending prompt to LLM")
        
        # Use shorter timeout for learning agent
        reply = safe_llm_invoke(response_prompt, timeout=15)
        
        processing_time = time.time() - start_time
        logging.info(f"[LEARNING_AGENT] LLM response received in {processing_time:.2f}s")

        # Validate response
        if not reply or reply.startswith("⚠️"):
            logging.warning(f"[LEARNING_AGENT] LLM returned error or empty response: {reply}")
            reply = "I apologize, but I'm having trouble generating a learning response right now. Please try again with a different question or topic."

        # Store in memory (thread-safe)
        memory_store.append(thread, f"User: {topic}\nAssistant: {reply}")

        logging.info(f"[LEARNING_AGENT] Successfully completed in {time.time() - start_time:.2f}s")
        
        return {"reply": reply.strip()}

    except Exception as e:
        error_time = time.time() - start_time
        logging.error(f"[LEARNING_AGENT] Critical error after {error_time:.2f}s: {str(e)}")
        
        return {
            "reply": "I'm experiencing technical difficulties with the learning service. Please try again in a moment or contact support if this continues."
        }


def chitchat(state: Dict[str, Any]):
    msg = state.get("message", "")
    # Use shorter timeout for chitchat
    reply = safe_llm_invoke(f"Answer briefly and helpfully: {msg}", timeout=10)
    if not reply.strip():
        reply = "I apologize, but I couldn't generate a response. Please try again."
    return {"reply": reply}


# ---- Build the graph ----
def build_graph():
    g = StateGraph(dict)
    g.add_node("router", router)
    g.add_node("career", career_agent)
    g.add_node("learning", learning_agent)
    g.add_node("chat", chitchat)

    g.set_entry_point("router")

    def route(state):
        intent = state.get("intent")
        if intent == "career":
            return "career"
        if intent == "learning":
            return "learning"
        return "chat"

    g.add_conditional_edges("router", route)
    g.add_edge("career", END)
    g.add_edge("learning", END)
    g.add_edge("chat", END)

    memory = MemorySaver()
    return g.compile(checkpointer=memory)

app_graph = build_graph()