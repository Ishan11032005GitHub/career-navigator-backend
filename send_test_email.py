import pickle
import base64
from email.mime.text import MIMEText
from googleapiclient.discovery import build

def send_email():
    with open('token.pickle', 'rb') as token:
        creds = pickle.load(token)

    service = build('gmail', 'v1', credentials=creds)

    message = MIMEText('This is a test email from CareerNavigatorAI backend!')
    message['to'] = 'ishan11032005@gmail.com'
    message['from'] = 'ishan11032005@gmail.com'
    message['subject'] = 'Gmail API test'

    raw_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}

    sent = service.users().messages().send(userId="me", body=raw_message).execute()
    print(f"✅ Email sent successfully! Message ID: {sent['id']}")

if __name__ == "__main__":
    send_email()
