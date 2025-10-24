import base64
import pickle
from email.mime.text import MIMEText
from googleapiclient.discovery import build

def send_email(recipient_email: str, subject: str, body: str):
    """Send an email via Gmail API (authorized using token.pickle)."""
    try:
        with open("token.pickle", "rb") as token:
            creds = pickle.load(token)

        service = build("gmail", "v1", credentials=creds)

        message = MIMEText(body)
        message["to"] = recipient_email
        message["from"] = "ishan11032005@gmail.com"   # replace with your Gmail
        message["subject"] = subject

        raw_message = {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}

        service.users().messages().send(userId="me", body=raw_message).execute()
        print(f"✅ Email sent successfully to {recipient_email}")

    except Exception as e:
        print(f"❌ Email sending failed: {e}")
