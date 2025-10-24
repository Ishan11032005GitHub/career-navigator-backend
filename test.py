import smtplib
from email.mime.text import MIMEText

sender = "your_email@gmail.com"
receiver = "ishan11032005@gmail.com"  # send to yourself first
app_password = "djdhtlmkabxnlpoy"  # replace with new 16-char code

msg = MIMEText("Test email from Career Navigator AI.")
msg["Subject"] = "SMTP Test"
msg["From"] = sender
msg["To"] = receiver

try:
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, app_password)
        server.send_message(msg)
    print("✅ Email sent successfully!")
except Exception as e:
    print("❌ Email sending failed:", e)