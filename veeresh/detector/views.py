import os
from django.db import models
import json
import random
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from .models import User, LungReport, UserOTP, Consultation, Prescription
from .utils import generate_otp, send_otp, send_sms_gateway
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string, get_template
from xhtml2pdf import pisa
from io import BytesIO
import numpy as np
from PIL import Image
import logging
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

from .model_utils import predict_dual, LABELS

# Removed local load_lung_model in favor of model_utils


def home_view(request):
    """Dedicated upload page."""
    return render(request, 'detector/home.html')


# PDF Generator Helper
def link_callback(uri, rel):
    """
    Convert HTML URIs to absolute system paths so xhtml2pdf can access those
    resources on local disk
    """
    import os
    from django.conf import settings
    
    # Handle media and static
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
    elif uri.startswith(settings.STATIC_URL):
        path = os.path.join(settings.STATIC_ROOT, uri.replace(settings.STATIC_URL, ""))
    else:
        return uri

    # make sure that file exists
    if not os.path.isfile(path):
        return uri
    return path

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("utf-8")), result, link_callback=link_callback)
    if not pdf.err:
        return result.getvalue()
    return None

def send_status_notification(report, request):
    # Prepare absolute URI for the result page
    full_report_url = request.build_absolute_uri(reverse('report_detail', args=[report.id]))
    booking_url = request.build_absolute_uri(reverse('book_consultation', args=[report.id]))
    
    # Email Notification
    subject = f"Clinical Update: Your Report #{report.id} has been {report.status}"
    
    extra_instruction = ""
    if report.status == 'Rejected' or (report.status == 'Approved' and report.result_label != 'Normal'):
        extra_instruction = f"\n\nIMPORTANT: Based on your results, we recommend booking a follow-up consultation. You can do so here: {booking_url}"

    message = f"Hello {report.patient.username},\n\n" \
              f"The clinical review of your lung scan (ID #{report.id}) has been completed.\n\n" \
              f"Final Status: {report.status.upper()}\n" \
              f"Reviewed By: Dr. {report.reviewed_by.username}\n\n" \
              f"Clinical Notes:\n\"{report.review_notes}\"\n\n" \
              f"You can view your detailed report here: {full_report_url}" \
              f"{extra_instruction}\n\n" \
              f"Stay healthy,\nLungQuest Team"
    
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [report.patient.email])
    except Exception as e:
        print(f"Error sending status email: {e}")

    # SMS Notification
    sms_msg = f"Your LungQuest report #{report.id} was {report.status.lower()}. "
    if report.status == 'Rejected' or (report.status == 'Approved' and report.result_label != 'Normal'):
        sms_msg += "Please login to book your follow-up consultation now."
    else:
        sms_msg += "Check your email/dashboard for full details."
        
    send_sms_gateway(report.patient.phone_number, sms_msg)

def send_consultation_request_notification(consultation, request):
    subject = f"Consultation Request Received: Dr. {consultation.doctor.username}"
    
    message = f"Hello {consultation.patient.username},\n\n" \
              f"We have successfully received your consultation request.\n\n" \
              f"Details:\n" \
              f"- Preferred Date: {consultation.preferred_date}\n" \
              f"- Mode: {consultation.mode}\n" \
              f"- Physician: Dr. {consultation.doctor.username}\n\n" \
              f"Your doctor will review this request and assign a specific time slot shortly. You will receive another notification once it is confirmed.\n\n" \
              f"Regards,\nLungQuest Medical Team"
              
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [consultation.patient.email])
        sms_msg = f"Your consultation request with Dr. {consultation.doctor.username} for {consultation.preferred_date} has been received. We will notify you once confirmed."
        send_sms_gateway(consultation.patient.phone_number, sms_msg)
    except Exception as e:
        print(f"Error sending consultation request email: {e}")

def send_consultation_notification(consultation, request):
    subject = f"Appointment Confirmed: Consultation with Dr. {consultation.doctor.username}"
    
    # Message content with the user's specific requirement
    message = f"Hello {consultation.patient.username},\n\n" \
              f"Your consultation request has been confirmed and scheduled.\n\n" \
              f"Details:\n" \
              f"- Date: {consultation.preferred_date}\n" \
              f"- Time: {consultation.scheduled_time}\n" \
              f"- Mode: {consultation.mode}\n" \
              f"- Physician: Dr. {consultation.doctor.username}\n\n" \
              f"IMPORTANT INSTRUCTIONS:\n" \
              f"Please be ready and join the portal at least 15 minutes early to ensure your connection and medical documents are prepared.\n\n" \
              f"You can access your dashboard here: {request.build_absolute_uri(reverse('patient_dashboard'))}\n\n" \
              f"Regards,\nLungQuest Medical Team"
              
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [consultation.patient.email])
        # Also SMS
        sms_msg = f"Your consultation with Dr. {consultation.doctor.username} is scheduled for {consultation.preferred_date} at {consultation.scheduled_time}. Please be 15 mins early."
        send_sms_gateway(consultation.patient.phone_number, sms_msg)
    except Exception as e:
        print(f"Error sending consultation email: {e}")

# Views

def landing_page(request):
    return render(request, 'detector/cover.html')

def signup_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        country_code = request.POST.get('country_code', '+91')
        phone_number_raw = request.POST.get('phone_number_raw', '')
        phone_number = f"{country_code}{phone_number_raw}"
        role = request.POST.get('role', 'patient')
        specialization = request.POST.get('specialization', '')
        license_number = request.POST.get('license_number', '')
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return redirect('signup')
            
        user = User.objects.create_user(
            username=username, 
            email=email, 
            password=password, 
            role=role, 
            phone_number=phone_number,
            specialization=specialization,
            license_number=license_number
        )
        
        # Generate and Send OTP
        otp = generate_otp()
        UserOTP.objects.create(user=user, otp_code=otp)
        success, msg = send_otp(user, otp, contact_method='email', otp_type='verification')
        
        if not success:
            messages.warning(request, f"OTP Delivery Notice: {msg}. Since you are in development mode, please check your terminal console for the OTP code.")
        
        request.session['unverified_user_id'] = user.id
        return redirect('verify_otp')
        
    return render(request, 'detector/signup.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        login_role = request.POST.get('login_role', 'patient')
        captcha_answer = request.POST.get('captcha_answer')
        
        expected_captcha = request.session.get('captcha_expected')
        
        if not captcha_answer or str(expected_captcha) != str(captcha_answer):
            messages.error(request, "Invalid Captcha. Please try again.")
            return redirect('login')
            
        user = authenticate(username=username, password=password)
        
        if user:
            # Check if user role matches selected login role
            if user.role != login_role:
                messages.error(request, f"Access denied. This account is registered as a {user.role}, not a {login_role}.")
                return redirect('login')
                
            login(request, user)
            return redirect('dashboard_redirect')
        else:
            messages.error(request, "Invalid credentials.")
            
    # Generate simple math captcha for GET request
    num1 = random.randint(1, 9)
    num2 = random.randint(1, 9)
    request.session['captcha_expected'] = num1 + num2
    
    return render(request, 'detector/login.html', {'num1': num1, 'num2': num2})

def verify_otp(request):
    user_id = request.session.get('unverified_user_id')
    if not user_id:
        return redirect('login')
        
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        otp_obj = UserOTP.objects.filter(
            user=user,
            otp_code=otp_input,
            created_at__gte=timezone.now() - timedelta(minutes=10)  # Bug fix #3: OTP expires after 10 min
        ).first()
        
        if otp_obj:
            user.is_verified = True
            user.save()
            otp_obj.delete()
            login(request, user)
            request.session.pop('unverified_user_id', None)
            return redirect('dashboard_redirect')
        else:
            messages.error(request, "Incorrect or expired OTP code. Please try again.")
            
    return render(request, 'detector/verify_otp.html', {'user': user})

def logout_view(request):
    logout(request)
    return redirect('landing')

@login_required
def dashboard_redirect(request):
    if request.user.role == 'doctor':
        return redirect('doctor_dashboard')
    return redirect('patient_dashboard')

@login_required
def patient_dashboard(request):
    reports = LungReport.objects.filter(patient=request.user).order_by('-created_at')
    doctors = User.objects.filter(role='doctor', is_verified=True)
    
    from .models import Consultation, Prescription
    from django.utils import timezone
    from datetime import timedelta
    
    consultations = Consultation.objects.filter(patient=request.user).order_by('-created_at')
    prescriptions = Prescription.objects.filter(patient=request.user).order_by('-created_at')
    
    # Calculate eligible reports for follow-up consultations
    eligible_reports = []
    for report in reports:
        if report.status in ['Rejected', 'Approved'] and not (report.status == 'Approved' and report.result_label == 'Normal'):
            latest_consultation = report.consultations.order_by('-created_at').first()
            if latest_consultation:
                if latest_consultation.status in ['Requested', 'Scheduled']:
                    continue  # Already has an active consultation
                
                if latest_consultation.next_consultation_date:
                    days_remaining = (latest_consultation.next_consultation_date - timezone.now().date()).days
                    next_date = latest_consultation.next_consultation_date
                else:
                    # Fallback for old consultations
                    days_passed = (timezone.now() - latest_consultation.created_at).days
                    days_remaining = 15 - days_passed
                    next_date = latest_consultation.created_at + timedelta(days=15)
                
                if days_remaining > 0:
                    eligible_reports.append({
                        'report': report,
                        'is_ready': False,
                        'next_date': next_date,
                        'days_remaining': days_remaining
                    })
                else:
                    eligible_reports.append({
                        'report': report,
                        'is_ready': True,
                        'next_date': timezone.now(),
                        'days_remaining': 0
                    })
            else:
                eligible_reports.append({
                    'report': report,
                    'is_ready': True,
                    'next_date': timezone.now(),
                    'days_remaining': 0
                })
    
    return render(request, 'detector/patient_dashboard.html', {
        'reports': reports,
        'available_doctors': doctors,
        'consultations': consultations,
        'prescriptions': prescriptions,
        'eligible_reports': eligible_reports,
        'pending_count': reports.filter(status='Pending').count(),
        'normal_count': reports.filter(result_label='Normal').count()
    })

@login_required
def doctor_dashboard(request):
    if request.user.role != 'doctor':
        return redirect('patient_dashboard')
    
    # Show reports specifically requested for this doctor, or general pending ones
    pending_reports = LungReport.objects.filter(
        status='Pending'
    ).filter(
        models.Q(requested_doctor=request.user) | models.Q(requested_doctor__isnull=True)
    ).order_by('-created_at')
    
    reviewed_reports = LungReport.objects.filter(reviewed_by=request.user).order_by('-reviewed_at')
    
    from .models import Consultation
    consultation_requests = Consultation.objects.filter(doctor=request.user, status='Requested').order_by('-created_at')
    scheduled_consultations = Consultation.objects.filter(doctor=request.user, status='Scheduled').order_by('preferred_date')

    # KPI stats — Bug fix #1: provide stats for dashboard cards
    week_ago = timezone.now() - timedelta(days=7)
    approved_week = LungReport.objects.filter(reviewed_by=request.user, status='Approved', reviewed_at__gte=week_ago).count()
    rejected_week = LungReport.objects.filter(reviewed_by=request.user, status='Rejected', reviewed_at__gte=week_ago).count()
    unique_patients = LungReport.objects.filter(reviewed_by=request.user).values('patient').distinct().count()
    
    # Scans directly uploaded by the doctor
    uploaded_scans = LungReport.objects.filter(patient=request.user).order_by('-created_at')

    consultation_history = Consultation.objects.filter(doctor=request.user, status__in=['Completed', 'Cancelled']).order_by('-created_at')

    return render(request, 'detector/doctor_dashboard.html', {
        'pending_reports': pending_reports,
        'reviewed_reports': reviewed_reports,
        'consultation_requests': consultation_requests,
        'scheduled_consultations': scheduled_consultations,
        'consultation_history': consultation_history,
        'approved_week': approved_week,
        'rejected_week': rejected_week,
        'unique_patients': unique_patients,
        'uploaded_scans': uploaded_scans,
    })

@login_required
def upload_scan(request):
    if request.method == 'POST' and request.FILES.get('image'):
        image_file = request.FILES['image']
        
        # Preprocessing & Prediction
        try:
            results = predict_dual(image_file)
            preds_json = results
            
            # Use ensemble for final label
            ensemble = results['ensemble']
            result_label = max(ensemble, key=ensemble.get)
            confidence = ensemble[result_label]

            patient = request.user
            # If a doctor uploads, they can optionally specify a patient_id
            target_patient_id = request.POST.get('target_patient')
            if request.user.role == 'doctor' and target_patient_id:
                patient = get_object_or_404(User, id=target_patient_id)

            report = LungReport.objects.create(
                patient=patient,
                image=image_file,
                prediction_json=preds_json,
                confidence=confidence,
                result_label=result_label,
                status='Unrequested' if patient == request.user else 'Pending', # Auto-request if doc uploads for someone
                patient_notes = request.POST.get('patient_notes', '')
            )
            return redirect('report_detail', report_id=report.id)
            
        except Exception as e:
            messages.error(request, f"Error processing image: {e}")
            return redirect('patient_dashboard')
            
    return redirect('patient_dashboard')

@login_required
def request_approval(request, report_id):
    report = get_object_or_404(LungReport, id=report_id, patient=request.user)
    if report.status == 'Unrequested':
        if request.method == 'POST':
            doctor_id = request.POST.get('doctor_id')
            if doctor_id:
                doctor = get_object_or_404(User, id=doctor_id, role='doctor')
                report.requested_doctor = doctor
            
            report.status = 'Pending'
            report.save()
            messages.success(request, f"Your report has been successfully sent to Dr. {report.requested_doctor.username if report.requested_doctor else 'our medical team'}. Your review will be processed shortly.")
            return redirect('patient_dashboard')
            
    return redirect('report_detail', report_id=report.id)

@login_required
def report_detail(request, report_id):
    report = get_object_or_404(LungReport, id=report_id)
    # Security check: only owner or any doctor can see
    if request.user.role == 'patient' and report.patient != request.user:
        return redirect('patient_dashboard')
    
    available_doctors = User.objects.filter(role='doctor', is_verified=True)
    context = {
        'report': report,
        'clinical_info': report.get_clinical_info,
        'predictions': report.prediction_json.get('ensemble'),
        'model_tf_results': report.prediction_json.get('model_tf'),
        'model_pt_results': report.prediction_json.get('model_pt'),
        'available_doctors': available_doctors,
    }
    return render(request, 'detector/result.html', context)

@login_required
def review_report(request, report_id):
    if request.user.role != 'doctor':
        return redirect('patient_dashboard')
        
    report = get_object_or_404(LungReport, id=report_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes')
        
        report.status = action
        report.review_notes = notes
        report.reviewed_by = request.user
        report.reviewed_at = timezone.now()
        
        # If doctor flags anomalies on a scan the AI thought was Normal, update label
        if action == 'Rejected' and report.result_label == 'Normal':
            report.result_label = 'Abnormal'
            
        report.save()
        
        # Send Notifications to Patient
        send_status_notification(report, request)
        
        messages.success(request, f"Report {report.status.lower()} successfully and patient notified.")
        return redirect('doctor_dashboard')
        
    return render(request, 'detector/review_report.html', {'report': report})

@login_required
def approve_report_otp(request, report_id):
    if request.user.role != 'doctor':
        return redirect('patient_dashboard')
        
    review_data = request.session.get('pending_review')
    if not review_data or review_data['report_id'] != report_id:
        return redirect('doctor_dashboard')
        
    report = get_object_or_404(LungReport, id=report_id)
    
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        otp_obj = UserOTP.objects.filter(
            user=request.user,
            otp_code=otp_input,
            created_at__gte=timezone.now() - timedelta(minutes=10)  # Bug fix #3: OTP expires after 10 min
        ).first()
        
        if otp_obj:
            report.status = review_data['action']
            report.review_notes = review_data['notes']
            report.reviewed_by = request.user
            report.reviewed_at = timezone.now()  # Bug fix #5: stamp the actual review time
            report.save()
            
            # Send Notifications to Patient
            send_status_notification(report, request)
            
            otp_obj.delete()
            request.session.pop('pending_review', None)
            messages.success(request, f"Report {report.status.lower()} successfully and patient notified.")
            return redirect('doctor_dashboard')
        else:
            messages.error(request, "Incorrect or expired OTP code. Please try again.")
            
    return render(request, 'detector/doctor_otp.html', {'report': report})

@login_required
def schedule_consultation(request, consultation_id):
    from .models import Consultation
    consultation = get_object_or_404(Consultation, id=consultation_id)
    
    if request.user != consultation.doctor:
        messages.error(request, 'Unauthorized.')
        return redirect('doctor_dashboard')
        
    if request.method == 'POST':
        time_slot = request.POST.get('time_slot')
        scheduled_date = request.POST.get('scheduled_date')
        if time_slot and scheduled_date:
            consultation.preferred_date = scheduled_date
            consultation.scheduled_time = time_slot
            consultation.status = 'Scheduled'
            consultation.save()
            
            # Notify Patient
            send_consultation_notification(consultation, request)
            
            messages.success(request, f'Consultation with {consultation.patient.username} scheduled and patient notified.')
        
    return redirect('doctor_dashboard')

@login_required
def book_consultation(request, report_id):
    from .models import Consultation
    report = get_object_or_404(LungReport, id=report_id)
    
    # Security: Only the patient who owns the report can book it, and only if approved
    if request.user != report.patient:
        messages.error(request, 'You do not have permission to book a consultation for this report.')
        return redirect('dashboard_redirect')
        
    if report.status not in ['Approved', 'Rejected']:
        messages.error(request, 'You can only book a consultation for verified or flagged reports.')
        return redirect('report_detail', report_id=report.id)

    if report.status == 'Approved' and report.result_label == 'Normal':
        messages.error(request, 'Your scan result is Normal and verified. A follow-up consultation is not required.')
        return redirect('report_detail', report_id=report.id)

    from django.utils import timezone
    from datetime import timedelta

    # Check if an active/pending consultation already exists
    if report.consultations.filter(status__in=['Requested', 'Scheduled']).exists():
        messages.warning(request, 'You already have an active consultation request for this report.')
        return redirect('patient_dashboard')

    # Enforce doctor-specified cooldown from the most recent consultation
    latest_consultation = report.consultations.order_by('-created_at').first()
    if latest_consultation:
        if latest_consultation.next_consultation_date:
            days_remaining = (latest_consultation.next_consultation_date - timezone.now().date()).days
            if days_remaining > 0:
                messages.warning(request, f'Your doctor recommended waiting until {latest_consultation.next_consultation_date.strftime("%B %d, %Y")} to book your next consultation. ({days_remaining} days remaining).')
                return redirect('patient_dashboard')
        else:
            days_passed = (timezone.now() - latest_consultation.created_at).days
            if days_passed < 15:
                messages.warning(request, f'You must wait 15 days between consultations for the same report. You can book again in {15 - days_passed} days.')
                return redirect('patient_dashboard')

    if request.method == 'POST':
        date = request.POST.get('date')
        notes = request.POST.get('notes', '')
        mode = request.POST.get('mode', 'Online')
        
        consultation = Consultation.objects.create(
            report=report,
            patient=request.user,
            doctor=report.reviewed_by,
            preferred_date=date,
            patient_notes=notes,
            mode=mode,
            status='Requested'
        )
        send_consultation_request_notification(consultation, request)
        messages.success(request, f'Your {mode} consultation request has been sent! Dr. {report.reviewed_by.username} will assign a specific time slot shortly.')
        return redirect('patient_dashboard')

    return render(request, 'detector/book_consultation.html', {'report': report})

@login_required
def generate_pdf(request, report_id):
    report = get_object_or_404(LungReport, id=report_id)
    # Security check
    if request.user.role == 'patient' and report.patient != request.user:
        return redirect('patient_dashboard')
        
    context = {
        'report': report,
        'clinical_info': report.get_clinical_info,
        'predictions': report.prediction_json.get('ensemble'),
        'model_tf_results': report.prediction_json.get('model_tf'),
        'model_pt_results': report.prediction_json.get('model_pt'),
    }
    
    pdf = render_to_pdf('detector/report_pdf.html', context)
    if pdf:
        response = HttpResponse(pdf, content_type='application/pdf')
        filename = f"Report_LQR_{report.id:05d}.pdf"
        content = f"inline; filename={filename}"
        response['Content-Disposition'] = content
        return response
    return HttpResponse("Error generating PDF", status=500)

@login_required
def email_report(request, report_id):
    report = get_object_or_404(LungReport, id=report_id)
    if report.patient != request.user and request.user.role != 'doctor':
        return JsonResponse({'status': 'error', 'message': 'Unauthorized'}, status=403)
    
    subject = f"Your LungQuest AI Diagnostic Report - ID #{report.id}"
    
    # Generate absolute URIs for email content
    full_report_url = request.build_absolute_uri(reverse('report_detail', args=[report_id]))
    full_image_url = request.build_absolute_uri(report.image.url)
    
    context = {
        'report': report,
        'clinical_info': report.get_clinical_info,
        'predictions': report.prediction_json.get('ensemble'),
        'model_tf_results': report.prediction_json.get('model_tf'),
        'model_pt_results': report.prediction_json.get('model_pt'),
        'full_report_url': full_report_url,
        'full_image_url': full_image_url,
    }
    html_message = render_to_string('detector/report_email_template.html', context)
    
    try:
        # Generate PDF for attachment
        pdf_content = render_to_pdf('detector/report_pdf.html', context)
        
        email = EmailMessage(
            subject,
            "Please find your lung scan report attached as a PDF.",
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email]
        )
        email.body = "Hello, your lung diagnostic report is attached to this email for your records."
        email.content_subtype = "html" # Optional if you want to use html_message as well
        email.body = html_message # Use the nice summary as body
        
        if pdf_content:
            email.attach(f"Report_LQR_{report.id:05d}.pdf", pdf_content, 'application/pdf')
            
        email.send()
        messages.success(request, f"Report PDF successfully sent to {request.user.email}")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")
        
    return redirect('report_detail', report_id=report.id)

@login_required
def clear_all_reports(request):
    reports = LungReport.objects.filter(patient=request.user)
    count = reports.count()
    if count > 0:
        reports.delete()
        messages.success(request, f"Successfully cleared {count} reports from your history.")
    else:
        messages.info(request, "No reports found to clear.")
    return redirect('patient_dashboard')

@login_required
def delete_report(request, report_id):
    report = get_object_or_404(LungReport, id=report_id)
    # Only patient who owns it or a superuser can delete
    if report.patient == request.user or request.user.is_superuser:
        report.delete()
        messages.success(request, "Report engagement deleted permanently.")
    else:
        messages.error(request, "Unauthorized action.")
    return redirect('dashboard_redirect')

@login_required
def delete_account(request, user_id):
    user_to_delete = get_object_or_404(User, id=user_id)
    # Can delete own account or if current user is superuser
    if request.user.id == user_id or request.user.is_superuser:
        user_to_delete.delete()
        if request.user.id == user_id:
            logout(request)
            messages.success(request, "Your account has been deleted.")
            return redirect('landing')
        messages.success(request, f"User {user_to_delete.username} deleted.")
    return redirect('dashboard_redirect')

@login_required
def user_management(request):
    if not request.user.is_superuser:
        return redirect('dashboard_redirect')
    all_users = User.objects.all().order_by('-date_joined')
    return render(request, 'detector/user_management.html', {'all_users': all_users})

@login_required
def profile_view(request):
    if request.method == 'POST':
        user = request.user
        user.phone_number = request.POST.get('phone_number', user.phone_number)
        
        if user.role == 'patient':
            user.smoking_history = request.POST.get('smoking_history', user.smoking_history)
            user.medical_conditions = request.POST.get('medical_conditions', user.medical_conditions)
            user.allergies = request.POST.get('allergies', user.allergies)
            user.current_medications = request.POST.get('current_medications', user.current_medications)
        
        user.save()
        messages.success(request, "Clinical profile updated successfully.")
        return redirect('profile')
        
    return render(request, 'detector/profile.html', {'target_user': request.user})

@login_required
def export_data(request):
    import csv
    if not request.user.is_superuser and request.user.role != 'doctor':
        messages.error(request, "Unauthorized access to clinical data export.")
        return redirect('dashboard_redirect')
        
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="lung_disease_data_export.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Report ID', 'Patient', 'Diagnosis', 'Confidence', 'Status', 'Reviewer', 'Created At'])
    
    reports = LungReport.objects.all().order_by('-created_at')
    for r in reports:
        writer.writerow([
            r.id, 
            r.patient.username, 
            r.result_label, 
            f"{r.confidence:.2f}%", 
            r.status, 
            r.reviewed_by.username if r.reviewed_by else 'N/A', 
            r.created_at.strftime('%Y-%m-%d %H:%M')
        ])
        
    return response

@login_required
def system_analytics(request):
    if not request.user.is_superuser and request.user.role != 'doctor':
        messages.error(request, "Unauthorized access to system analytics.")
        return redirect('dashboard_redirect')
        
    total_reports = LungReport.objects.count()
    from collections import Counter
    results = LungReport.objects.values_list('result_label', flat=True)
    stats_counter = Counter(results)
    
    chart_data = {
        'labels': list(stats_counter.keys()),
        'values': list(stats_counter.values())
    }
    
    return render(request, 'detector/analytics.html', {
        'total_reports': total_reports,
        'chart_data_json': json.dumps(chart_data)
    })

def about_view(request):
    return render(request, 'detector/about.html')

def resources_view(request):
    return render(request, 'detector/resources.html')


# ─── Auto-refresh JSON endpoints ──────────────────────────────────────────────

@login_required
def patient_dashboard_data(request):
    """Returns live report statuses + KPI counts for the patient dashboard poller."""
    reports = LungReport.objects.filter(patient=request.user).order_by('-created_at')
    data = {
        'total':   reports.count(),
        'normal':  reports.filter(result_label='Normal').count(),
        'pending': reports.filter(status='Pending').count(),
        'reports': [
            {
                'id':     r.id,
                'status': r.status,
                'reviewed_by': r.reviewed_by.username if r.reviewed_by else None,
                'requested_doctor': r.requested_doctor.username if r.requested_doctor else None,
            }
            for r in reports
        ],
    }
    return JsonResponse(data)


@login_required
def doctor_dashboard_data(request):
    """Returns pending queue count + KPI stats for the doctor dashboard poller."""
    if request.user.role != 'doctor':
        return JsonResponse({'error': 'forbidden'}, status=403)

    from django.db.models import Q
    week_ago = timezone.now() - timedelta(days=7)

    pending_qs = LungReport.objects.filter(
        status='Pending'
    ).filter(
        Q(requested_doctor=request.user) | Q(requested_doctor__isnull=True)
    )

    # Serialize the pending queue rows so JS can add newly arrived scans
    pending_list = [
        {
            'id':           r.id,
            'patient':      r.patient.username,
            'patient_id':   r.patient.id,
            'date':         r.created_at.strftime('%b %d, %Y · %H:%M'),
            'result_label': r.result_label,
            'confidence':   round(r.confidence, 1),
            'requested_for_you': r.requested_doctor_id == request.user.id,
        }
        for r in pending_qs.order_by('-created_at')
    ]

    data = {
        'pending_count':   pending_qs.count(),
        'approved_week':   LungReport.objects.filter(reviewed_by=request.user, status='Approved',  reviewed_at__gte=week_ago).count(),
        'rejected_week':   LungReport.objects.filter(reviewed_by=request.user, status='Rejected',  reviewed_at__gte=week_ago).count(),
        'unique_patients': LungReport.objects.filter(reviewed_by=request.user).values('patient').distinct().count(),
        'pending_reports': pending_list,
    }
    return JsonResponse(data)


@login_required
def video_call(request, consultation_id):
    consultation = get_object_or_404(Consultation, id=consultation_id)
    if request.user != consultation.patient and request.user != consultation.doctor:
        return HttpResponse('Unauthorized', status=401)
    
    room_name = f"LungQuest-Consultation-{consultation.id}-{consultation.patient.username}"
    return render(request, 'detector/video_call.html', {
        'consultation': consultation,
        'room_name': room_name,
        'user_name': request.user.username
    })

@login_required
def write_prescription(request, consultation_id):
    if request.user.role != 'doctor':
        return HttpResponse('Unauthorized', status=401)
        
    consultation = get_object_or_404(Consultation, id=consultation_id, doctor=request.user)
    
    if request.method == 'POST':
        medications = request.POST.get('medications')
        doctor_notes = request.POST.get('doctor_notes')
        next_consultation_date = request.POST.get('next_consultation_date')
        
        prescription, created = Prescription.objects.update_or_create(
            consultation=consultation,
            defaults={
                'doctor': request.user,
                'patient': consultation.patient,
                'medications': medications,
                'doctor_notes': doctor_notes
            }
        )
        consultation.status = 'Completed'
        if next_consultation_date:
            consultation.next_consultation_date = next_consultation_date
        consultation.save()
        
        # Generate PDF and Email Patient
        pdf_bytes = render_to_pdf('detector/prescription_pdf.html', {'prescription': prescription})
        if pdf_bytes:
            from django.core.mail import EmailMessage
            from .utils import send_sms_gateway
            
            subject = f"Your Medical Prescription from Dr. {request.user.username}"
            message = f"Hello {consultation.patient.username},\n\nYour consultation with Dr. {request.user.username} has been completed.\n\nPlease find your official medical prescription attached to this email.\n\nRegards,\nLungQuest Medical Team"
            
            email = EmailMessage(subject, message, settings.DEFAULT_FROM_EMAIL, [consultation.patient.email])
            email.attach(f"prescription_{consultation.patient.username}.pdf", pdf_bytes, 'application/pdf')
            try:
                email.send(fail_silently=True)
                sms_msg = f"Your consultation is complete. Dr. {request.user.username} has issued your prescription. Please check your email."
                send_sms_gateway(consultation.patient.phone_number, sms_msg)
            except Exception as e:
                print(f"Error sending prescription email: {e}")
                
        messages.success(request, 'Prescription saved and emailed to patient successfully.')
        return redirect('doctor_dashboard')
        
    return render(request, 'detector/prescription_form.html', {'consultation': consultation})

@login_required
def compare_scans(request, patient_id):
    patient = get_object_or_404(User, id=patient_id)
    if request.user.role != 'doctor' and request.user != patient:
        return HttpResponse('Unauthorized', status=401)
        
    # Get all approved scans for this patient, ordered by date
    scans = LungReport.objects.filter(patient=patient, status='Approved').order_by('-created_at')
    
    if scans.count() < 2:
        messages.warning(request, "Patient needs at least two approved scans to compare.")
        if request.user.role == 'doctor':
            return redirect('doctor_dashboard')
        return redirect('patient_dashboard')
        
    return render(request, 'detector/compare_scans.html', {'scans': scans, 'patient': patient})

@login_required
def end_consultation(request, consultation_id):
    if request.user.role != 'doctor':
        return HttpResponse('Unauthorized', status=401)
        
    consultation = get_object_or_404(Consultation, id=consultation_id, doctor=request.user)
    
    if request.method == 'POST':
        next_consultation_date = request.POST.get('next_consultation_date')
        consultation.status = 'Completed'
        if next_consultation_date:
            consultation.next_consultation_date = next_consultation_date
        consultation.save()
        messages.success(request, 'Consultation ended successfully.')
        return redirect('doctor_dashboard')
        
    # If accessed via GET, just render the modal form or redirect (usually POST is used now)
    return redirect('doctor_dashboard')

@login_required
def prescription_pdf(request, prescription_id):
    prescription = get_object_or_404(Prescription, id=prescription_id)
    if request.user != prescription.patient and request.user != prescription.doctor:
        return HttpResponse('Unauthorized', status=401)
        
    template = get_template('detector/prescription_pdf.html')
    html = template.render({'prescription': prescription})
    
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="prescription_{prescription.patient.username}.pdf"'
        return response
    return HttpResponse('Error generating PDF')
