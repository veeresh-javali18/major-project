import os
import django
from django.core.mail import send_mail
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'lung_disease_pro.settings')
django.setup()

try:
    print("Attempting to send test email with NEW credentials...")
    send_mail(
        'Test Email',
        'This is a test email from LungQuest AI using new credentials.',
        settings.DEFAULT_FROM_EMAIL,
        [settings.EMAIL_HOST_USER], # Send to self
        fail_silently=False,
    )
    print("SUCCESS: Test email sent successfully!")
except Exception as e:
    print(f"FAILED: {e}")
