# /opt/easyportfolio_django_app/easyportfolio_project/urls.py

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path("admin/", admin.site.urls),
    path("portfolio/", include("portfolio_app.urls", namespace="portfolio_app")), # URLs deiner App
    
    # URLs für Djangos Authentifizierungssystem (Login, Logout, Passwort Reset etc.)
    path("accounts/", include("django.contrib.auth.urls")), 
]
