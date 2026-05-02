from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing'),
    path('home/', views.home_view, name='home'),
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('verify-otp/', views.verify_otp, name='verify_otp'),
    path('logout/', views.logout_view, name='logout'),
    path('profile/', views.profile_view, name='profile'),
    
    path('dashboard/', views.dashboard_redirect, name='dashboard_redirect'),
    path('patient/dashboard/', views.patient_dashboard, name='patient_dashboard'),
    path('doctor/dashboard/', views.doctor_dashboard, name='doctor_dashboard'),
    
    path('scan/upload/', views.upload_scan, name='upload_scan'),
    path('report/<int:report_id>/request-approval/', views.request_approval, name='request_approval'),
    path('report/<int:report_id>/', views.report_detail, name='report_detail'),
    path('report/<int:report_id>/review/', views.review_report, name='review_report'),
    path('report/<int:report_id>/approve-otp/', views.approve_report_otp, name='approve_report_otp'),
    path('report/<int:report_id>/pdf/', views.generate_pdf, name='report_pdf'),
    path('report/<int:report_id>/email/', views.email_report, name='email_report'),
    path('report/<int:report_id>/delete/', views.delete_report, name='delete_report'),
    path('report/<int:report_id>/book/', views.book_consultation, name='book_consultation'),
    path('consultation/<int:consultation_id>/schedule/', views.schedule_consultation, name='schedule_consultation'),
    path('reports/clear-all/', views.clear_all_reports, name='clear_all_history'),
    path('user/<int:user_id>/delete/', views.delete_account, name='delete_account'),
    path('manage/users/', views.user_management, name='user_management'),
    path('manage/export/', views.export_data, name='export_data'),
    path('manage/analytics/', views.system_analytics, name='system_analytics'),
    path('about/', views.about_view, name='about'),
    path('resources/', views.resources_view, name='resources'),

    # Auto-refresh JSON endpoints
    path('api/patient-data/', views.patient_dashboard_data, name='patient_dashboard_data'),
    path('api/doctor-data/',  views.doctor_dashboard_data,  name='doctor_dashboard_data'),
    
    # Advanced Features
    path('consultation/<int:consultation_id>/video/', views.video_call, name='video_call'),
    path('consultation/<int:consultation_id>/prescribe/', views.write_prescription, name='write_prescription'),
    path('consultation/<int:consultation_id>/end/', views.end_consultation, name='end_consultation'),
    path('prescription/<int:prescription_id>/pdf/', views.prescription_pdf, name='prescription_pdf'),
    path('patient/<int:patient_id>/compare/', views.compare_scans, name='compare_scans'),
]


