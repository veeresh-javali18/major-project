from django.db import models
from django.contrib.auth.models import AbstractUser
import json

class User(AbstractUser):
    ROLE_CHOICES = (
        ('patient', 'Patient'),
        ('doctor', 'Doctor'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='patient')
    specialization = models.CharField(max_length=100, blank=True, null=True)
    license_number = models.CharField(max_length=50, blank=True, null=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.username} ({self.role})"

class LungReport(models.Model):
    STATUS_CHOICES = (
        ('Unrequested', 'Awaiting Action'),
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    )
    patient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scans')
    image = models.ImageField(upload_to='scans/')
    prediction_json = models.JSONField()
    confidence = models.FloatField()
    result_label = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Unrequested')
    requested_doctor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_scans')
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    review_notes = models.TextField(blank=True, null=True)
    patient_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report for {self.patient.username} - {self.result_label}"

    @property
    def get_clinical_info(self):
        info_map = {
            'Lung Opacity': {
                'description': 'Lung opacity is a finding on a chest X-ray or CT scan where an area of the lung appears denser or more solid than the air-filled tissue around it. It can be caused by various factors including fluid, solid masses, or scarring. This condition often requires further clinical correlation and possibly follow-up scans or biopsies to determine the underlying cause. It is frequently associated with complications in breathing or localized chest pain.',
                'severity': 'Medium',
                'badge_color': '#ff9800',
                'precautions': [
                    'Schedule a follow-up CT scan in 3-6 months as advised.',
                    'Absolutely avoid smoking or exposure to second-hand smoke.',
                    'Monitor for any new chest pain or persistent coughing.',
                    'Consult a Pulmonologist for a specialized diagnostic workup.'
                ]
            },
            'COVID-19': {
                'description': 'COVID-19 is a highly infectious respiratory illness caused by the SARS-CoV-2 virus, often manifesting as bilateral ground-glass opacities on medical imaging. It can lead to severe inflammation of the lungs, significantly reducing oxygen exchange and causing high levels of respiratory distress. Beyond the lungs, it may affect other organ systems through systemic inflammation. Management involves close monitoring of vital signs and oxygen saturation.',
                'severity': 'High',
                'badge_color': '#f44336',
                'precautions': [
                    'Immediate isolation to prevent the spread of infection.',
                    'Continuous monitoring of oxygen levels using a pulse oximeter.',
                    'Maintain high hydration and rest as much as possible.',
                    'Keep a log of symptoms and seek emergency care if breathing worsens.'
                ]
            },
            'Pneumonia': {
                'description': 'Pneumonia is an infection that inflames the air sacs in one or both lungs, which may fill with fluid or pus, causing cough, fever, chills, and difficulty breathing. A variety of organisms, including bacteria, viruses, and fungi, can cause pneumonia. It can range in seriousness from mild to life-threatening, particularly in infants, the elderly, and those with weakened immune systems. Prompt medical intervention is often necessary.',
                'severity': 'High',
                'badge_color': '#e91e63',
                'precautions': [
                    'Complete the full course of prescribed antibiotics or antivirals.',
                    'Use a humidifier or stay in a well-ventilated, humid room.',
                    'Practice deep breathing exercises to help clear the lungs.',
                    'Avoid sudden temperature changes and cold drafts.'
                ]
            },
            'Normal': {
                'description': 'A normal finding indicates that the lung parenchyma is well-ventilated without any evidence of focal consolidation, effusion, or masses. The heart size and pulmonary vasculature appear within normal limits on the current imaging. This result suggests that there are no acute lung diseases detected by the AI analysis at this time. However, clinical correlation with ongoing symptoms is always advised for a complete medical diagnosis.',
                'severity': 'Low',
                'badge_color': '#4caf50',
                'precautions': [
                    'Maintain a balanced diet and regular exercise routine.',
                    'Prioritize respiratory hygiene and avoid smoky environments.',
                    'Consider annual flu and pneumonia vaccinations.',
                    'Regular health checkups to monitor lung capacity.'
                ]
            }
        }
        return info_map.get(self.result_label, {
            'description': 'No specific clinical data available for this finding.',
            'severity': 'Unknown',
            'badge_color': '#9e9e9e',
            'precautions': ['Consult your doctor for personalized advice.']
        })

class UserOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"OTP for {self.user.username}"
