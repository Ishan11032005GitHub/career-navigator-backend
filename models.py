# models.py
from pydantic import BaseModel
from typing import List, Optional

class ChatRequest(BaseModel):
    message: str
    thread_id: str = "default"
    resume_text: Optional[str] = None
    job_posts: Optional[list] = None  # list of {title, company, requirements: []}

class ChatResponse(BaseModel):
    reply: str
    pdf_path: Optional[str] = None
    latex_code: Optional[str] = None
    intent: Optional[str] = None

class STTRequest(BaseModel):
    # Frontend will send base64 wav/webm blob
    audio_b64: str
    thread_id: str = "default"

class STTResponse(BaseModel):
    text: str

class TTSRequest(BaseModel):
    text: str

class TTSResponse(BaseModel):
    audio_b64: str