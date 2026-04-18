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
from .models import User, LungReport, UserOTP
from django.http import JsonResponse, HttpResponse
from django.template.loader import render_to_string, get_template
from xhtml2pdf import pisa
from io import BytesIO
import numpy as np
from PIL import Image
from twilio.rest import Client
import logging

logger = logging.getLogger(__name__)

from .model_utils import predict_dual, LABELS

# Removed local load_lung_model in favor of model_utils

# Helper to generate OTP
def generate_otp():
    return ''.join(random.choices(string.digits, k=6))

def send_otp_email(user, otp):
    subject = "Your Verification Code - LungQuest AI"
    message = f"Hello {user.username},\n\nYour 6-digit verification code is: {otp}\n\nThis code is valid for 10 minutes.\n\nStay healthy,\nLungQuest Team"
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])

def send_otp_sms(user, otp):
    message = f"Your LungQuest AI verification code is: {otp}. Valid for 10 minutes."
    send_sms_gateway(user.phone_number, message)

def send_sms_gateway(to_number, message_body):
    """
    Simulation Mode: Prints to console. 
    (Real Twilio integration code is preserved but deactivated)
    """
    print(f"\n[SIMULATED NOTIFICATION] To: {to_number} | Message: {message_body}\n")
    return True

    # Real Twilio code (commented out for now):
    # sid = settings.TWILIO_ACCOUNT_SID
    # ...


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
    
    # Email Notification
    subject = f"Clinical Update: Your Report #{report.id} has been {report.status}"
    message = f"Hello {report.patient.username},\n\n" \
              f"The clinical review of your lung scan (ID #{report.id}) has been completed.\n\n" \
              f"Final Status: {report.status.upper()}\n" \
              f"Reviewed By: Dr. {report.reviewed_by.username}\n\n" \
              f"Clinical Notes:\n\"{report.review_notes}\"\n\n" \
              f"You can view your detailed report here: {full_report_url}\n\n" \
              f"Stay healthy,\nLungQuest Team"
    
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [report.patient.email])
    except Exception as e:
        print(f"Error sending status email: {e}")

    # SMS Notification
    sms_msg = f"Your LungQuest diagnostic report #{report.id} has been {report.status.lower()} by Dr. {report.reviewed_by.username}. Check your email for full details."
    send_sms_gateway(report.patient.phone_number, sms_msg)

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
        send_otp_email(user, otp)
        
        request.session['unverified_user_id'] = user.id
        return redirect('verify_otp')
        
    return render(request, 'detector/signup.html')

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        login_role = request.POST.get('login_role', 'patient')
        user = authenticate(username=username, password=password)
        
        if user:
            # Check if user role matches selected login role
            if user.role != login_role:
                messages.error(request, f"Access denied. This account is registered as a {user.role}, not a {login_role}.")
                return redirect('login')
                
            # Always send OTP for security on every login
            otp = generate_otp()
            UserOTP.objects.create(user=user, otp_code=otp)
            send_otp_email(user, otp)
            request.session['unverified_user_id'] = user.id
            return redirect('verify_otp')
        else:
            messages.error(request, "Invalid credentials.")
            
    return render(request, 'detector/login.html')

def verify_otp(request):
    user_id = request.session.get('unverified_user_id')
    if not user_id:
        return redirect('login')
        
    user = get_object_or_404(User, id=user_id)
    
    if request.method == 'POST':
        otp_input = request.POST.get('otp')
        otp_obj = UserOTP.objects.filter(user=user, otp_code=otp_input).first()
        
        if otp_obj:
            user.is_verified = True
            user.save()
            otp_obj.delete()
            login(request, user)
            request.session.pop('unverified_user_id', None)
            return redirect('dashboard_redirect')
        else:
            messages.error(request, "Incorrect OTP code.")
            
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
    return render(request, 'detector/patient_dashboard.html', {
        'reports': reports,
        'available_doctors': doctors,
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
    
    reviewed_reports = LungReport.objects.filter(reviewed_by=request.user).order_by('-created_at')
    return render(request, 'detector/doctor_dashboard.html', {
        'pending_reports': pending_reports,
        'reviewed_reports': reviewed_reports
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
            messages.success(request, f"Approval request sent to {report.requested_doctor.username if report.requested_doctor else 'our medical team'}.")
            return redirect('patient_dashboard')
            
    return redirect('report_detail', report_id=report.id)

@login_required
def report_detail(request, report_id):
    report = get_object_or_404(LungReport, id=report_id)
    # Security check: only owner or any doctor can see
    if request.user.role == 'patient' and report.patient != request.user:
        return redirect('patient_dashboard')
    
    context = {
        'report': report,
        'clinical_info': report.get_clinical_info,
        'predictions': report.prediction_json.get('ensemble'),
        'model_tf_results': report.prediction_json.get('model_tf'),
        'model_pt_results': report.prediction_json.get('model_pt'),
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
        
        # Before finalizing, we need OTP for doc
        request.session['pending_review'] = {
            'report_id': report.id,
            'action': action,
            'notes': notes
        }
        
        otp = generate_otp()
        UserOTP.objects.create(user=request.user, otp_code=otp)
        send_otp_email(request.user, otp)
        
        return redirect('approve_report_otp', report_id=report.id)
        
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
        otp_obj = UserOTP.objects.filter(user=request.user, otp_code=otp_input).first()
        
        if otp_obj:
            report.status = review_data['action']
            report.review_notes = review_data['notes']
            report.reviewed_by = request.user
            report.save()
            
            # Send Notifications to Patient
            send_status_notification(report, request)
            
            otp_obj.delete()
            request.session.pop('pending_review', None)
            messages.success(request, f"Report {report.status.lower()} successfully and patient notified.")
            return redirect('doctor_dashboard')
        else:
            messages.error(request, "Incorrect OTP code.")
            
    return render(request, 'detector/doctor_otp.html', {'report': report})

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
    return render(request, 'detector/profile.html', {'target_user': request.user})

def about_view(request):
    return render(request, 'detector/about.html')

def resources_view(request):
    return render(request, 'detector/resources.html')
