#!/usr/bin/env python3
"""
Startup verification script - Run this before deploying
Checks all imports and dependencies to catch issues early
"""
import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def check_imports():
    """Verify all critical imports work"""
    checks = [
        ("FastAPI", lambda: __import__("fastapi")),
        ("SQLite3", lambda: __import__("sqlite3")),
        ("Pydantic", lambda: __import__("pydantic")),
        ("python-jose", lambda: __import__("jose")),
        ("LangGraph", lambda: __import__("langgraph")),
        ("PyMuPDF (fitz)", lambda: __import__("fitz")),
        ("Requests", lambda: __import__("requests")),
        ("Spacy", lambda: __import__("spacy")),
    ]
    
    failed = []
    for name, importer in checks:
        try:
            importer()
            logging.info(f"✅ {name}")
        except ImportError as e:
            logging.error(f"❌ {name}: {e}")
            failed.append(name)
    
    return len(failed) == 0

def check_app_imports():
    """Verify app modules import correctly"""
    modules = [
        ("models", lambda: __import__("models")),
        ("auth", lambda: __import__("auth")),
        ("database", lambda: __import__("database")),
        ("email_utils", lambda: __import__("email_utils")),
        ("tools", lambda: __import__("tools")),
        ("graph", lambda: __import__("graph")),
    ]
    
    failed = []
    for name, importer in modules:
        try:
            importer()
            logging.info(f"✅ Module: {name}")
        except Exception as e:
            logging.error(f"❌ Module {name}: {e}")
            failed.append(name)
    
    return len(failed) == 0

def check_database():
    """Verify database can be created/accessed"""
    try:
        from database import get_db
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        logging.info("✅ Database access")
        return True
    except Exception as e:
        logging.error(f"❌ Database access: {e}")
        return False

def check_main_app():
    """Verify main app initializes"""
    try:
        # This will import and initialize the app
        from main import app, startup_event
        logging.info("✅ Main app initialization")
        return True
    except Exception as e:
        logging.error(f"❌ Main app initialization: {e}")
        return False

if __name__ == "__main__":
    logging.info("=" * 60)
    logging.info("STARTUP VERIFICATION")
    logging.info("=" * 60)
    
    all_passed = True
    
    logging.info("\n[1/4] Checking external dependencies...")
    all_passed &= check_imports()
    
    logging.info("\n[2/4] Checking app modules...")
    all_passed &= check_app_imports()
    
    logging.info("\n[3/4] Checking database...")
    all_passed &= check_database()
    
    logging.info("\n[4/4] Checking main app...")
    all_passed &= check_main_app()
    
    logging.info("\n" + "=" * 60)
    if all_passed:
        logging.info("✅ ALL CHECKS PASSED - Ready to deploy!")
        logging.info("=" * 60)
        sys.exit(0)
    else:
        logging.error("❌ SOME CHECKS FAILED - Fix issues before deploying")
        logging.info("=" * 60)
        sys.exit(1)
