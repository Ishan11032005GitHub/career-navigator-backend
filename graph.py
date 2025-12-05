import os, sys, re, json, time, uuid, tempfile, shutil, subprocess, threading, logging, requests
from typing import Dict, Any
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
import fitz  # PyMuPDF

from tools import analyze_resume, match_jobs, generate_learning_path, quick_quiz

# ==========================================================
# CONFIG
# ==========================================================
DATA_ROOT = os.getenv("DATA_ROOT", r"C:\career_ai_data")
GEN_DIR = os.path.join(DATA_ROOT, "generated_resumes")
os.makedirs(GEN_DIR, exist_ok=True)

if not load_dotenv():
    print("⚠️ Warning: .env file not found", file=sys.stderr)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ==========================================================
# THREAD SAFE MEMORY
# ==========================================================
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
            if len(self._store[thread_id]) > 10:
                self._store[thread_id] = self._store[thread_id][-10:]


memory_store = ThreadSafeMemoryStore()

# ==========================================================
# SAFE LLM INVOKE
# ==========================================================
def safe_llm_invoke(prompt: str, timeout: int = 30) -> str:
    start_time = time.time()
    if len(prompt) > 4000:
        prompt = prompt[:4000] + "... [truncated]"

    # Try OpenRouter
    try:
        openrouter_key = os.getenv('OPENROUTER_API_KEY', '').strip()
        if not openrouter_key:
            logging.warning("[LLM] OPENROUTER_API_KEY not configured")
        else:
            logging.info("[LLM] Sending prompt to OpenRouter")
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "openai/gpt-4o",
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 500,
                    "temperature": 0.7
                },
                timeout=timeout
            )
            if response.status_code == 200:
                data = response.json()
                if "choices" in data and data["choices"]:
                    text = data["choices"][0]["message"]["content"].strip()
                    if text:
                        logging.info(f"[LLM] OpenRouter response in {time.time() - start_time:.2f}s")
                        return text
            else:
                logging.warning(f"[LLM] OpenRouter returned status {response.status_code}: {response.text[:200]}")
    except Exception as e:
        logging.error(f"[LLM] OpenRouter failed: {e}", exc_info=True)

    # Try Hugging Face
    try:
        hf_key = os.getenv("HF_API_KEY", "").strip()
        if not hf_key:
            logging.warning("[LLM] HF_API_KEY not configured")
        else:
            logging.info("[LLM] Falling back to Hugging Face")
            response = requests.post(
                "https://api-inference.huggingface.co/models/google/gemma-2-2b-it",
                headers={"Authorization": f"Bearer {hf_key}"},
                json={"inputs": prompt},
                timeout=timeout
            )
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and result and "generated_text" in result[0]:
                    text = result[0]["generated_text"].replace(prompt, "").strip()
                    if text:
                        logging.info(f"[LLM] HF response in {time.time() - start_time:.2f}s")
                        return text
            else:
                logging.warning(f"[LLM] HF returned status {response.status_code}: {response.text[:200]}")
    except Exception as e:
        logging.error(f"[LLM] HF inference failed: {e}", exc_info=True)

    logging.error("[LLM] All LLM providers failed, using fallback response")
    return enhanced_fallback_response(prompt)


# ==========================================================
# FALLBACK RESPONSES
# ==========================================================
def enhanced_fallback_response(prompt: str) -> str:
    p = prompt.lower()
    if any(w in p for w in ["resume", "cv", "career", "job", "apply"]):
        return """I can help you with resume optimization and career guidance.

Upload your resume text and I can:
• Identify skill gaps
• Suggest improvements
• Generate a professional LaTeX resume
• Recommend tailored job roles."""
    if "sql" in p or "database" in p:
        return """**SQL Learning Path**
1. SELECT, WHERE, ORDER BY
2. INSERT, UPDATE, DELETE
3. JOINS (INNER, LEFT, RIGHT)
4. GROUP BY, HAVING
5. Subqueries and indexes."""
    if "python" in p:
        return """**Python Learning Guide**
• Basics: variables, loops, functions
• Data structures: lists, dicts, sets
• OOP principles
• Libraries: Pandas, Flask, Requests"""
    if "javascript" in p or "web" in p:
        return """**JavaScript Web Dev**
• DOM manipulation
• Async (Promises, async/await)
• React, Node.js basics"""
    if "learn" in p or "study" in p:
        return """**Smart Learning Tips**
1. Set goals
2. Practice consistently
3. Build small projects
4. Review and iterate."""
    return "I'm ready to help you with resume, job advice, or learning new tech topics. What would you like to focus on?"

# ==========================================================
# ROUTER
# ==========================================================
def router(state: Dict[str, Any]):
    text = (state.get("message") or "").lower()
    career_hits = sum(k in text for k in ["job", "resume", "apply", "hiring", "role"])
    learn_hits = sum(k in text for k in ["learn", "teach", "quiz", "study", "path"])
    if career_hits > learn_hits:
        return {"intent": "career"}
    elif learn_hits > 0:
        return {"intent": "learning"}
    return {"intent": "chat"}

# ==========================================================
# LATEX UTILITIES
# ==========================================================
def validate_and_fix_latex(code: str) -> str:
    code = code.replace(r"\{", "{").replace(r"\}", "}")
    code = re.sub(r"(?<!\\)begin\{", r"\\begin{", code)
    code = re.sub(r"(?<!\\)end\{", r"\\end{", code)
    return code

def is_valid_latex(code: str) -> bool:
    if not code:
        return False
    required = ["\\documentclass", "\\begin{document}", "\\end{document}"]
    return all(re.search(r, code, re.I) for r in required)

def get_fallback_latex_template(_: str) -> str:
    return r"""\documentclass[11pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{geometry}
\usepackage{enumitem}
\usepackage{hyperref}
\geometry{a4paper, margin=1in}
\setlist[itemize]{leftmargin=*}
\begin{document}
\begin{center}
{\LARGE \textbf{Professional Resume}}\\
\vspace{0.5cm}
{\large Software Engineer}
\end{center}
\section*{Skills}
\begin{itemize}
\item Python, JavaScript, Java, C++
\item React, Node.js, Express
\item Git, Docker, AWS
\end{itemize}
\end{document}"""

# ==========================================================
# CAREER AGENT
# ==========================================================
def career_agent(state: Dict[str, Any]):
    message = state.get("message", "")
    resume_text = (state.get("resume_text") or "").strip()
    if not resume_text:
        return {"reply": "⚠️ Please provide your resume text first."}

    resume_text_clean = re.sub(r"\\[a-zA-Z]+", "", resume_text)
    resume_text_clean = re.sub(r"[{}]", "", resume_text_clean)
    job_posts = state.get("job_posts") or []

    # Intent
    res = safe_llm_invoke(
        f"You are a classifier: respond with 'restructure' or 'analyze'.\nUser: {message}"
    ).lower()
    intent = "restructure" if "restructure" in res else "analyze"

    if intent == "analyze":
        analysis = analyze_resume(resume_text)
        ranked = match_jobs(analysis.get("skills", []), job_posts) if job_posts else []
        prompt = f"""You are a career coach.
User: {message}
Resume: {resume_text_clean[:4000]}
Detected skills: {analysis.get('skills', [])}
Top jobs: {[p.get('title') for p in ranked[:3]]}
Write a short actionable reply."""
        reply = safe_llm_invoke(prompt)
        return {"reply": reply.strip(), "intent": "analyze"}

    # Restructure
    latex_code = safe_llm_invoke(
        f"Generate a clean LaTeX resume based on this text:\n{resume_text_clean[:3000]}"
    )
    latex_code = validate_and_fix_latex(latex_code)
    if not is_valid_latex(latex_code):
        latex_code = get_fallback_latex_template(resume_text_clean)

    base = f"resume_{uuid.uuid4().hex}"
    tex_path = os.path.join(GEN_DIR, f"{base}.tex")
    pdf_path = os.path.join(GEN_DIR, f"{base}.pdf")
    preview_url = f"/generated_resumes/{base}.pdf"
    download_url = f"/download-pdf/{base}.pdf"

    try:
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(latex_code)
    except Exception as e:
        return {"reply": f"❌ Failed to write LaTeX file: {e}"}

    pdf_generated = False
    latex_output = ""

    try:
        tmp_dir = tempfile.mkdtemp(dir=GEN_DIR)
        shutil.copy(tex_path, tmp_dir)
        for i in range(2):
            res = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", os.path.basename(tex_path)],
                cwd=tmp_dir, capture_output=True, text=True, timeout=60
            )
            latex_output += res.stdout + res.stderr
        gen_pdf = os.path.join(tmp_dir, f"{base}.pdf")
        if os.path.exists(gen_pdf):
            shutil.move(gen_pdf, pdf_path)
            pdf_generated = True
        shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception as e:
        latex_output += str(e)

    if pdf_generated and os.path.getsize(pdf_path) > 1000:
        reply = "✅ Resume successfully restructured!"
    else:
        reply = "⚠️ LaTeX failed, generating simple PDF."
        fallback_pdf = os.path.join(GEN_DIR, f"{base}_simple.pdf")
        try:
            doc = fitz.open()
            page = doc.new_page()
            page.insert_textbox(fitz.Rect(50, 50, 500, 100),
                                "SOFTWARE ENGINEER RESUME",
                                fontsize=16, fontname="Helvetica-Bold")
            page.insert_textbox(fitz.Rect(50, 120, 550, 750),
                                resume_text_clean[:1500],
                                fontsize=10, fontname="Helvetica")
            doc.save(fallback_pdf)
            doc.close()
            pdf_generated = True
            preview_url = f"/generated_resumes/{base}_simple.pdf"
            download_url = f"/download-pdf/{base}_simple.pdf"
        except Exception as e:
            reply += f"\n❌ Fallback PDF failed: {e}"

    reply += (
        f"\n\n📥 [Download PDF]({download_url}) | [Preview]({preview_url})"
        f"\n\n---\n<details><summary>LaTeX Code</summary>\n<pre>{latex_code}</pre></details>"
    )
    if not pdf_generated:
        reply += f"\n<details><summary>Logs</summary><pre>{latex_output}</pre></details>"

    return {"reply": reply, "pdf_path": preview_url, "latex_code": latex_code, "intent": "restructure"}

# ==========================================================
# LEARNING AGENT
# ==========================================================
def learning_agent(state: Dict[str, Any], thread_id: str = "default"):
    start = time.time()
    thread = state.get("thread_id") or thread_id
    topic = state.get("message", "").strip()
    if not topic:
        return {"reply": "Please provide a topic or question to learn about."}

    history = memory_store.get(thread, [])
    context = "\n".join(history[-2:]) if history else "No previous context"
    prompt = f"""You are a helpful learning mentor.
Previous:
{context}
Question: "{topic}"
Answer briefly (under 300 words) with clear explanations and actionable steps."""
    
    reply = safe_llm_invoke(prompt, timeout=15)
    
    # Validate response before returning
    if not reply or not reply.strip():
        logging.error(f"[LEARNING_AGENT] Empty response received for topic: {topic}")
        reply = f"I couldn't generate a detailed response for '{topic}'. Please try rephrasing your question or provide more context."
    
    memory_store.append(thread, f"User: {topic}\nAssistant: {reply}")
    logging.info(f"[LEARNING_AGENT] Completed in {time.time()-start:.2f}s")
    return {"reply": reply.strip()}

# ==========================================================
# CHITCHAT
# ==========================================================
def chitchat(state: Dict[str, Any]):
    msg = state.get("message", "").strip()
    if not msg:
        return {"reply": "I didn't catch that. Please provide a message."}
    
    r = safe_llm_invoke(f"Answer conversationally and helpfully: {msg}", timeout=10)
    
    if not r or not r.strip():
        logging.error(f"[CHITCHAT] Empty response received for message: {msg}")
        return {"reply": "I'm having trouble processing that. Could you please rephrase your question?"}
    
    return {"reply": r.strip()}

# ==========================================================
# GRAPH BUILD
# ==========================================================
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
