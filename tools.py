# tools.py
from typing import List, Dict
import re

# ---- Career tools (simple, effective stubs you can improve fast) ----

def analyze_resume(text: str) -> Dict:
    """Very simple heuristic resume analyzer.
    Returns detected skills and suggestions.
    """
    skills_db = [
        "python", "java", "c++", "sql", "mongodb", "mysql", "react", "node",
        "express", "aws", "docker", "kubernetes", "git", "rest", "linux",
        "pandas", "numpy", "tensorflow", "pytorch"
    ]
    text_l = text.lower()
    found = sorted({s for s in skills_db if re.search(rf"\\b{s}\\b", text_l)})

    suggestions = []
    if "sql" not in found:
        suggestions.append("Add SQL with a concrete bullet (e.g., optimized 5 complex joins)")
    if "aws" not in found:
        suggestions.append("Mention basic cloud skills (AWS/GCP/Azure) if relevant")
    if "react" not in found and "node" not in found:
        suggestions.append("If applying for full-stack, include React/Node exposure")

    return {"skills": found, "suggestions": suggestions}


def match_jobs(skills: List[str], job_posts: List[Dict]) -> List[Dict]:
    """Return job posts sorted by naive skill overlap score."""
    def score(post):
        reqs = [s.lower() for s in post.get("requirements", [])]
        return len(set(skills) & set(reqs))

    ranked = sorted(job_posts, key=score, reverse=True)
    for p in ranked:
        p["match_score"] = len(set(skills) & set([s.lower() for s in p.get("requirements", [])]))
    return ranked


# ---- Learning tools ----

def generate_learning_path(topic: str) -> List[str]:
    base = topic.strip().title()
    return [
        f"{base}: Day 1 — Core concepts & hello world",
        f"{base}: Day 2 — Practice problems & mini project",
        f"{base}: Day 3 — Build a tiny app and write a README",
        f"{base}: Day 4 — Add tests & refactor",
        f"{base}: Day 5 — Ship a demo and share on GitHub",
    ]


def quick_quiz(topic: str) -> List[Dict]:
    t = topic.strip().lower()
    if "sql" in t:
        return [
            {"q": "What does SELECT do?", "a": "Retrieves rows/columns from a table."},
            {"q": "Write a query to get all names from employees.", "a": "SELECT name FROM employees;"},
        ]
    if "python" in t:
        return [
            {"q": "What is a list comprehension?", "a": "A compact syntax to create lists: [f(x) for x in xs]"},
            {"q": "How do you create a virtual environment?", "a": "python -m venv .venv && source .venv/bin/activate"},
        ]
    return [
        {"q": f"Name 2 fundamentals of {topic}", "a": "Answers vary"},
        {"q": f"Suggest a tiny project in {topic}", "a": "Answers vary"},
    ]