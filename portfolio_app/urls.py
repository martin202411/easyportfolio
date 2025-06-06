# /opt/easyportfolio_django_app/portfolio_app/urls.py #

from django.urls import path
from . import views

app_name = 'portfolio_app' 

urlpatterns = [
    path('', views.portfolio_startseite, name='startseite'),
    path('einzel-wp/', views.einzel_wp_ansicht, name='einzel_wp_ansicht'),
    path('datenmanagement/eodhd-hub/', views.eodhd_data_hub_view, name='eodhd_data_hub'),
    path('datenmanagement/eodhd-hub/import-security/', views.import_eodhd_security_view, name='import_eodhd_security'),
    path('datenmanagement/eodhd-hub/update-security/<int:security_id>/', views.update_eodhd_security_view, name='update_eodhd_security'),
    path('experten-portfolios/', views.experten_portfolio_ansicht_view, name='experten_portfolio_ansicht'),
    path('manager/', views.portfolio_manager_view, name='portfolio_manager'),
    path('portfolio-vergleich/', views.portfolio_vergleich_ansicht_view, name='portfolio_vergleich_ansicht'),
]
