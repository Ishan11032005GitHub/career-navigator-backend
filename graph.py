import os, sys, requests, json
from dotenv import load_dotenv
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import tempfile

from tools import analyze_resume, match_jobs, generate_learning_path, quick_quiz
import os, re, subprocess, uuid
import fitz  # PyMuPDF (already used in your project)

DATA_ROOT = os.getenv("DATA_ROOT", r"C:\career_ai_data")
GEN_DIR = os.path.join(DATA_ROOT, "generated_resumes")
os.makedirs(GEN_DIR, exist_ok=True)

# --- Load env file early ---
if not load_dotenv():
    print("⚠️ Warning: .env file not found", file=sys.stderr)


# --- Ollama config (free local LLM) ---
def _normalize_ollama_url(v: str) -> str:
    """
    Accept either:
      - http://localhost:11434
      - http://localhost:11434/
      - http://localhost:11434/api
      - http://localhost:11434/api/
      - http://localhost:11434/api/generate
    and normalize to .../api/generate
    """
    v = (v or "").strip()
    if not v:
        return "http://localhost:11434/api/generate"
    v = v.rstrip("/")
    if v.endswith("/api/generate"):
        return v
    if v.endswith("/api"):
        return v + "/generate"
    return v + "/api/generate"


# Keep your previous default behavior but robust to base URL envs too
OLLAMA_URL = _normalize_ollama_url(os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3:4b")


def _format_err(prefix: str, detail: str) -> str:
    return f"{prefix}: {detail}"


def _explain_ollama_http_error(resp: requests.Response) -> str:
    """
    Try to provide a helpful message when Ollama responds with a non-200.
    """
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    # Common issues:
    # - model not found
    text = str(data).lower()
    if resp.status_code == 404 or "model not found" in text or "no such model" in text:
        return _format_err("⚠️ Ollama error", f"Model '{OLLAMA_MODEL}' not found. Try: `ollama pull {OLLAMA_MODEL}`")
    return _format_err("⚠️ Ollama HTTP error", f"status={resp.status_code}, body={data}")


# ---- Ollama invoke ----
def safe_llm_invoke(prompt: str) -> str:
    """
    Send a prompt to Ollama and stream back the text output.
    Robust to Windows/PowerShell chunking and stray decode artifacts.
    """
    try:
        r = requests.post(
            OLLAMA_URL,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": True},
            stream=True,
            timeout=180,
        )

        if r.status_code != 200:
            return _explain_ollama_http_error(r)

        full = []
        # Ollama sends one JSON object per line when stream=True.
        # Read line-by-line and parse each independently (no cross-line buffering).
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Ignore any malformed fragments and keep going.
                continue

            if "response" in obj:
                full.append(obj["response"])
            if obj.get("done"):
                break

        text = "".join(full).strip()

        # Optional single-shot fallback if nothing arrived (keeps functionality same but more reliable)
        if not text:
            try:
                r2 = requests.post(
                    OLLAMA_URL,
                    json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                    timeout=60,
                )
                if r2.status_code == 200:
                    data2 = r2.json()
                    text = (data2.get("response") or "").strip()
                else:
                    return _explain_ollama_http_error(r2)
            except requests.exceptions.RequestException:
                # If even fallback fails, surface the original empty-stream message
                pass

        return text if text else "⚠️ Ollama produced no text (stream was empty)."

    except requests.exceptions.ConnectionError:
        return f"⚠️ Cannot reach Ollama at {OLLAMA_URL}. Please run `ollama serve`."
    except requests.exceptions.Timeout:
        return "⚠️ Ollama request timed out."
    except Exception as e:
        return f"⚠️ Unexpected error: {type(e).__name__}: {e}"


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


def learning_agent(state: Dict[str, Any], thread_id: str = "default"):
    # Allow thread_id to be passed either as arg (backend direct call) or via state (graph mode)
    thread = state.get("thread_id") or thread_id or "default"
    topic = state.get("message", "a topic")

    # Retrieve or create memory for this thread
    history = memory_store.get(thread, [])
    context_text = "\n".join(history[-3:])  # last 3 exchanges

    # Build a contextual prompt
    mainSubject = safe_llm_invoke(
        f"Extract the main subject(s) of this request in 1–3 words max: {topic}"
    ).strip()

    response_prompt = f"""
You are a helpful learning mentor. Maintain context of previous chats:
{context_text}

Current user question: "{topic}"
Main subject: {mainSubject}

Generate a 5-day roadmap OR detailed explanation, quiz, and mini project idea.
"""

    reply = safe_llm_invoke(response_prompt)
    if not reply.strip():
        reply = "⚠️ The model returned no content."

    history.append(f"User: {topic}\nAssistant: {reply}")
    memory_store[thread] = history
    return {"reply": reply}


def chitchat(state: Dict[str, Any]):
    msg = state.get("message", "")
    reply = safe_llm_invoke(f"Answer briefly and helpfully: {msg}")
    if not reply.strip():
        reply = "⚠️ The model returned no content."
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