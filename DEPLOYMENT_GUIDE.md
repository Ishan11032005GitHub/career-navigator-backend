# Deployment Guide - Career Navigator Backend

## ✅ Pre-Deployment Checklist

### 1. Local Testing
```bash
# Run startup verification
python startup_check.py

# Expected: ✅ ALL CHECKS PASSED - Ready to deploy!
```

### 2. Environment Variables Required
Make sure these are set in Railway (or your deployment platform):

```env
# OpenRouter API (recommended)
OPENROUTER_API_KEY=your_openrouter_key_here

# Hugging Face (fallback)
HF_API_KEY=your_hf_token_here

# Authentication
SECRET_KEY=generate_a_random_secret_key

# Email (Gmail API - optional)
GMAIL_CREDENTIALS_FILE=token.pickle
```

### 3. Common Issues & Solutions

#### ❌ 502 Bad Gateway / Connection Refused
**Cause**: App not starting, likely import errors
**Solution**:
1. Check Railway logs: `railway logs`
2. Run `python startup_check.py` locally to identify issues
3. Ensure all environment variables are set
4. Check that no required files are missing

#### ❌ Module Import Errors
**Cause**: Missing dependencies or circular imports
**Solution**:
```bash
pip install -r requirements.txt
python -c "import main"  # Should not error
```

#### ❌ Database Connection Errors
**Cause**: Wrong database path or permissions
**Solution**:
- On Linux/Railway: `/app/data/career_ai.db` (auto-created)
- On Windows: `C:\career_ai_data\career_ai.db` (auto-created)
- Ensure `/app/data` directory exists and is writable

### 4. Health Check Endpoints

```bash
# Quick health check (always works)
curl https://your-app.up.railway.app/health

# Response: {"status": "healthy", "message": "API is running"}

# Detailed health check (includes all systems)
curl https://your-app.up.railway.app/health/detailed

# Response shows status of database, career_agent, learning_agent
```

### 5. Deployment Steps (Railway)

1. **Connect repository** to Railway
2. **Set environment variables**:
   - Go to Variables in Railway dashboard
   - Add all required environment variables
   - See section 2 above
3. **Deploy**:
   - Push to `main` branch (auto-deploys)
   - Or manually redeploy from Railway dashboard
4. **Monitor**:
   - Check Railway logs for errors
   - Visit `/health/detailed` endpoint
   - Check that database is being created

### 6. Verifying Production Deployment

```bash
# Replace with your actual deployment URL
BASE_URL="https://career-navigator-backend-production.up.railway.app"

# 1. Check health
curl $BASE_URL/health

# 2. Check detailed health
curl $BASE_URL/health/detailed

# 3. Test signup (should work but may fail on email if credentials missing)
curl -X POST $BASE_URL/api/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "username": "testuser",
    "password": "password123"
  }'

# 4. Test login
curl -X POST $BASE_URL/api/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123"
  }'
```

### 7. Recent Fixes Applied

✅ Lazy-loaded agent imports (prevents startup failure)
✅ Better error handling in `safe_llm_invoke()`
✅ Added comprehensive health check endpoints
✅ Defensive imports with fallback implementations
✅ Improved logging for debugging

### 8. Common Log Patterns to Look For

**Good signs:**
```
✅ Core modules imported successfully
✅ Learning agent imported successfully
✅ Career agent imported successfully
Running on http://0.0.0.0:8000
```

**Warning signs:**
```
❌ Failed to import
connection refused
traceback
ModuleNotFoundError
```

### 9. If Still Getting 502 Errors

1. **Check Railway logs**:
   ```bash
   railway logs --follow
   ```

2. **Look for**:
   - Import errors (ModuleNotFoundError, ImportError)
   - Missing environment variables
   - Database permission issues
   - Infinite loops or deadlocks

3. **Test locally first**:
   ```bash
   python startup_check.py
   uvicorn main:app --reload
   ```

4. **Check dependencies**:
   ```bash
   pip install -r requirements.txt --upgrade
   ```

### 10. Rollback Plan

If deployment fails:
1. Revert last commit: `git revert HEAD`
2. Push to main: `git push`
3. Railway auto-deploys
4. Check logs: `railway logs`

---

**Questions?** Check the detailed health endpoint: `/health/detailed`
