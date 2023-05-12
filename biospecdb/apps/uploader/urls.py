from django.urls import path

from . import views


app_name = "uploader"

urlpatterns = [
    path("", views.index, name="index"),
    path("<int:patient_id>/", views.patient_data, name="patient_data"),
    path("<int:patient_id>/samples", views.samples, name="samples"),
]
