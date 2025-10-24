# auth.py
import os, hashlib, secrets
from datetime import datetime, timedelta
from jose import JWTError, jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from database import get_db

load_dotenv()
SECRET = os.getenv("SECRET_KEY", "supersecret")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 4
security = HTTPBearer()

def hash_password(pw: str): 
    return hashlib.sha256(pw.encode()).hexdigest()

def verify_password(pw, hashed): 
    return hash_password(pw) == hashed

def create_token(username: str):
    payload = {"sub": username, "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        return payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# --- Forgot password token (short-lived)
def create_reset_token(email: str):
    payload = {"sub": email, "exp": datetime.utcnow() + timedelta(minutes=15)}
    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)

def verify_reset_token(token: str):
    try:
        data = jwt.decode(token, SECRET, algorithms=[ALGORITHM])
        return data.get("sub")
    except JWTError:
        return None
