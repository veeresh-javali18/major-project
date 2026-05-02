import random
import string
from django.core.mail import send_mail
from django.conf import settings
import logging
from twilio.rest import Client

logger = logging.getLogger(__name__)

def generate_otp(length=6):
    """Generate a random numeric OTP."""
    return ''.join(random.choices(string.digits, k=length))

def send_otp_email(user, otp):
    subject = "Your Verification Code - LungQuest AI"
    message = f"Hello {user.username},\n\nYour 6-digit verification code is: {otp}\n\nThis code is valid for 10 minutes.\n\nStay healthy,\nLungQuest Team"
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
        return True, "OTP sent to email"
    except Exception as e:
        logger.error(f"Error sending email: {e}")
        return False, str(e)

def send_sms_gateway(to_number, message_body):
    """
    Sends a real SMS using Twilio.
    """
    if not to_number:
        return False, "No phone number provided"
        
    try:
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(
            body=message_body,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to_number
        )
        return True, "OTP sent to mobile"
    except Exception as e:
        logger.error(f"Twilio Error: {e}")
        # Fallback to console print for debugging
        print(f"\n[FALLBACK CONSOLE] To: {to_number} | Message: {message_body}\n")
        return False, str(e)

def send_otp_sms(user, otp):
    message = f"Your LungQuest AI verification code is: {otp}. Valid for 10 minutes."
    return send_sms_gateway(user.phone_number, message)

def send_otp(user, otp, contact_method='email', otp_type='login'):
    """
    Centralized OTP sending dispatcher.
    """
    if contact_method == 'email':
        return send_otp_email(user, otp)
    elif contact_method == 'sms':
        return send_otp_sms(user, otp)
    return False, "Invalid contact method"
