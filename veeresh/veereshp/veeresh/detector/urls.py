from django.urls import path
from . import views

urlpatterns = [
    path('', views.landing_page, name='landing'),
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
    path('user/<int:user_id>/delete/', views.delete_account, name='delete_account'),
    path('admin/users/', views.user_management, name='user_management'),
    path('about/', views.about_view, name='about'),
    path('resources/', views.resources_view, name='resources'),
]


