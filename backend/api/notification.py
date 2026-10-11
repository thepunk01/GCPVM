import smtplib
from core.enums import OperationType
from email.message import EmailMessage

def send_email(sender, receiver, condition, password):
    if not sender or not password or not receiver:
        # Notifications are optional. A missing SMTP configuration must not
        # mark a successful GCP operation as failed in its background task.
        return
    msg = EmailMessage()
    server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
    server.login(sender, password)
    if condition == OperationType.START:
        msg.set_content("Server has been started")
    elif condition == OperationType.STOP:
        msg.set_content("Server has been stopped")
    msg['Subject'] = str(condition)
    msg['From'] = sender
    msg['To'] = receiver
    server.send_message(msg)
    server.quit()

