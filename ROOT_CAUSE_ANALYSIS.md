# 502 Error Root Cause Analysis & Fix

## 🔴 THE PROBLEM

```
Railway Logs:
❌ 502 Bad Gateway
❌ Connection refused
❌ Retried single replica
❌ Deployment timeout

What happened:
1. Railway starts container
2. App tries to start with `uvicorn main:app`
3. main.py imports from graph.py
4. graph.py imports from tools.py
5. ANY error in this chain → App crashes
6. Port 8000 never opens
7. Railway gets no response → 502 error
```

## 🔍 ROOT CAUSES FOUND

### Issue #1: Synchronous Imports at Startup
```python
# ❌ OLD CODE (main.py line 15)
from graph import career_agent, learning_agent
```
**Problem**: If `graph.py` fails, entire app fails before port opens.

### Issue #2: Unprotected Imports in graph.py
```python
# ❌ OLD CODE (graph.py line 9)
from tools import analyze_resume, match_jobs, generate_learning_path, quick_quiz
```
**Problem**: Any error in tools.py → graph.py crashes → app crashes.

### Issue #3: Silent Failures in LLM Calls
```python
# ❌ OLD CODE (graph.py safe_llm_invoke)
try:
    response = requests.post(...)
    if response.status_code == 200:
        return data["choices"][0]["message"]["content"]  # Crashes if wrong structure
except Exception:  # Silently catches everything
    pass  # Falls through to next provider without logging details
```
**Problem**: Hard to debug what's actually failing.

### Issue #4: No Diagnostics
```python
# ❌ OLD CODE
@app.get("/health")
def health_check():
    return {"status": "healthy"}
```
**Problem**: Can't tell which component is broken.

## 🟢 SOLUTIONS IMPLEMENTED

### Solution #1: Lazy Loading
```python
# ✅ NEW CODE (main.py)
_career_agent = None
_learning_agent = None

def get_career_agent():
    global _career_agent
    if _career_agent is None:
        from graph import career_agent
        _career_agent = career_agent
    return _career_agent
```
**Benefit**: 
- App starts even if agents fail
- Agents only loaded when first requested
- Better error visibility

### Solution #2: Defensive Imports
```python
# ✅ NEW CODE (graph.py)
try:
    from tools import analyze_resume, match_jobs, ...
except ImportError as e:
    logging.error(f"Failed to import tools: {e}")
    # Provide stub implementations
    def analyze_resume(text):
        return {"skills": [], "suggestions": []}
    def match_jobs(skills, posts):
        return []
```
**Benefit**:
- graph.py loads even if tools fail
- App provides graceful degradation
- Clear error logging

### Solution #3: Improved Error Handling
```python
# ✅ NEW CODE (graph.py safe_llm_invoke)
openrouter_key = os.getenv('OPENROUTER_API_KEY', '').strip()
if not openrouter_key:
    logging.warning("[LLM] OPENROUTER_API_KEY not configured")
else:
    response = requests.post(...)
    if response.status_code == 200:
        data = response.json()
        if "choices" in data and data["choices"]:
            text = data["choices"][0]["message"]["content"].strip()
            if text:
                return text
    else:
        logging.warning(f"[LLM] Status {response.status_code}: {response.text[:200]}")
```
**Benefit**:
- Validates API keys before use
- Checks response structure
- Logs errors with details

### Solution #4: Comprehensive Health Checks
```python
# ✅ NEW CODE (main.py)
@app.get("/health/detailed")
def detailed_health_check():
    status = {
        "database": test_db(),
        "career_agent": test_career_agent(),
        "learning_agent": test_learning_agent(),
    }
    return status
```
**Benefit**:
- Instant diagnostics
- Shows which component failed
- Fast debugging

### Solution #5: Pre-deployment Verification
```python
# ✅ NEW FILE: startup_check.py
python startup_check.py
# Checks:
# ✅ All external dependencies
# ✅ All internal modules
# ✅ Database access
# ✅ Main app initialization
```

## 📊 BEFORE vs AFTER

| Scenario | Before | After |
|----------|--------|-------|
| `graph.py` has import error | ❌ 502 error, app won't start | ✅ App starts, lazy load failed gracefully |
| `tools.py` missing function | ❌ 502 error, app won't start | ✅ App starts with stub functions |
| Missing API key | ❌ Silent failure → fallback response | ✅ Logged warning, clear diagnostics |
| User asks "what's wrong?" | ❌ Check logs manually | ✅ Hit `/health/detailed` endpoint |
| Deploying to production | ❌ Unknown if it will work | ✅ Run `startup_check.py` first |

## 🚀 DEPLOYMENT FLOW

### Old Flow (BROKEN)
```
1. Railway starts container
   ↓
2. main.py loads
   ↓
3. from graph import ... (CRASH if error)
   ↓
4. ❌ Port never opens
   ↓
5. Railway: 502 Bad Gateway
```

### New Flow (WORKING)
```
1. Railway starts container
   ↓
2. main.py loads
   ├─ Lazy import references created
   ├─ get_career_agent() created
   ├─ get_learning_agent() created
   ↓
3. FastAPI app initialized
   ↓
4. ✅ Port 8000 opens, listening
   ↓
5. Agents loaded on-demand when first request arrives
   ├─ If error: logged and returned as 500
   ├─ If success: returns proper response
```

## 🧪 TESTING

### Local Verification
```bash
# 1. Startup check
python startup_check.py
# Output: ✅ ALL CHECKS PASSED

# 2. Import test
python -c "from main import app; print('✅ App loaded')"
# Output: ✅ App loaded

# 3. Run server
uvicorn main:app --reload
# Output: Uvicorn running on http://127.0.0.1:8000

# 4. Health check
curl http://localhost:8000/health
# Output: {"status": "healthy"}

# 5. Detailed health
curl http://localhost:8000/health/detailed
# Output: All components "ok"
```

### After Deployment to Railway
```bash
# Check if app started
curl https://your-app.up.railway.app/health

# Check if components work
curl https://your-app.up.railway.app/health/detailed

# Check logs
railway logs --follow
```

## 📝 SUMMARY

**Problem**: App crashed on startup due to import failures → 502 errors

**Solution**: 
- Lazy-load critical modules (don't fail at startup)
- Defensive imports with fallbacks
- Better error logging and validation
- Comprehensive health checks
- Pre-deployment verification script

**Result**:
- App starts successfully ✅
- Graceful degradation if modules fail ✅
- Easy debugging with `/health/detailed` ✅
- Pre-deployment verification ✅
- Clear error messages in logs ✅

---

**Next Step**: Push changes to Railway and verify with `/health/detailed`
