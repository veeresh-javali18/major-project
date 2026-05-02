from apscheduler.schedulers.background import BackgroundScheduler
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from datetime import timedelta
from dateutil import parser
import logging

logger = logging.getLogger(__name__)

def check_consultation_reminders():
    try:
        from detector.models import Consultation
        from detector.utils import send_sms_gateway
    except ImportError:
        return

    now = timezone.localtime(timezone.now())
    
    # We only care about Scheduled ones that haven't had a reminder sent yet
    upcoming = Consultation.objects.filter(status='Scheduled', reminder_sent=False)
    
    for consult in upcoming:
        if not consult.preferred_date or not consult.scheduled_time:
            continue
            
        try:
            # Parse the date and time.
            date_str = consult.preferred_date.strftime("%Y-%m-%d")
            time_str = consult.scheduled_time
            
            # Use dateutil parser to intelligently parse string like "2026-04-29 10:30 AM"
            datetime_str = f"{date_str} {time_str}"
            scheduled_dt = parser.parse(datetime_str)
            
            # Ensure it is timezone aware
            if timezone.is_naive(scheduled_dt):
                scheduled_dt = timezone.make_aware(scheduled_dt, timezone.get_current_timezone())
                
            time_diff = scheduled_dt - now
            
            # If the consultation is within the next 15 minutes
            if timedelta(minutes=0) <= time_diff <= timedelta(minutes=16):
                send_reminder(consult, send_sms_gateway)
                
                # Mark as sent
                consult.reminder_sent = True
                consult.save(update_fields=['reminder_sent'])
                
        except Exception as e:
            logger.error(f"Error parsing date/time for consultation {consult.id}: {e}")

def send_reminder(consult, sms_gateway_func):
    subject = f"Reminder: Your Consultation with Dr. {consult.doctor.username} is in 15 Minutes"
    
    message = f"Hello {consult.patient.username},\n\n" \
              f"This is a gentle reminder that your {consult.mode.lower()} consultation is starting in 15 minutes.\n\n" \
              f"Details:\n" \
              f"- Time: {consult.scheduled_time}\n" \
              f"- Physician: Dr. {consult.doctor.username}\n\n" \
              f"Please log into the portal to join.\n\n" \
              f"Regards,\nLungQuest Medical Team"
              
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [consult.patient.email])
        sms_msg = f"Reminder: Your consultation with Dr. {consult.doctor.username} starts in 15 mins. Please log in now."
        sms_gateway_func(consult.patient.phone_number, sms_msg)
    except Exception as e:
        logger.error(f"Error sending consultation reminder email: {e}")

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_consultation_reminders, 'interval', minutes=1, id='consultation_reminder_job', replace_existing=True)
    scheduler.start()
