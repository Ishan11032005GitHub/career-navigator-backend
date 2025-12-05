# Quick Fix Guide - 502 Bad Gateway Errors

## 🔴 You're Getting 502 Errors? Here's What Changed

Your app was crashing on startup because of import errors. We've fixed it with:

1. **Lazy-loaded agents** - Only load `career_agent` and `learning_agent` when needed
2. **Defensive imports** - Stub implementations as fallback if imports fail  
3. **Better error handling** - Detailed logging to identify what's breaking
4. **Health check endpoints** - Instant diagnostics

## 🟢 Deployment Instructions

### Step 1: Verify Locally
```bash
python startup_check.py
```
Should show: `✅ ALL CHECKS PASSED - Ready to deploy!`

### Step 2: Push to GitHub
```bash
git add -A
git commit -m "Fix 502 errors: lazy-load agents, defensive imports, health checks"
git push origin main
```

### Step 3: Railway Auto-Deploys
Once you push, Railway will automatically redeploy.

### Step 4: Verify Deployment
Check health once deployed:
```bash
curl https://career-navigator-backend-production.up.railway.app/health/detailed
```

## 🔍 Troubleshooting

### If Still Getting 502 Errors:

1. **Check the detailed health endpoint**
   ```bash
   curl https://your-app.up.railway.app/health/detailed
   ```
   This shows which component is failing.

2. **Check Railway logs**
   ```bash
   railway logs --follow
   ```
   Look for any error messages.

3. **Ensure environment variables are set**
   - Go to Railway dashboard
   - Variables section
   - Add required env vars:
     - `OPENROUTER_API_KEY` (for AI responses)
     - `HF_API_KEY` (fallback AI)
     - `SECRET_KEY` (authentication)

4. **Run locally to test**
   ```bash
   python startup_check.py
   uvicorn main:app --reload
   ```

## 📋 What Was Fixed

| Issue | Fix |
|-------|-----|
| App crashes if `graph.py` has errors | Lazy-load agents with `get_career_agent()` |
| Import errors crash entire app | Defensive imports with stub implementations |
| Hard to debug what's failing | Added `/health/detailed` endpoint |
| No way to catch issues pre-deploy | Created `startup_check.py` |
| Poor LLM error handling | Added API key validation and response checking |

## ✅ Files Modified

- `main.py` - Lazy loading, error handling, health checks
- `graph.py` - Defensive imports
- `Dockerfile` - Added startup verification

## 📄 Files Created

- `startup_check.py` - Pre-deployment verification
- `DEPLOYMENT_GUIDE.md` - Full deployment guide
- `FIX_502_ERRORS.md` - Detailed fix documentation

## 🚀 Quick Test After Deployment

```bash
# 1. Health check (quick)
curl https://your-app.up.railway.app/health

# 2. Detailed health (diagnostics)
curl https://your-app.up.railway.app/health/detailed

# 3. Test API
curl -X POST https://your-app.up.railway.app/api/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","username":"test","password":"test123"}'
```

## 🆘 Still Having Issues?

1. Check `/health/detailed` - it will tell you what's wrong
2. Read `DEPLOYMENT_GUIDE.md` for detailed troubleshooting
3. Check Railway logs for error details
4. Ensure all environment variables are set correctly

---

**TL;DR**: Push code, Railway auto-deploys, check `/health/detailed` endpoint to verify everything works.
