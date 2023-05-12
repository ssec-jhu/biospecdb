from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from uploader.models import Patient


def index(request):
    all_patients = Patient.objects.order_by("-age")
    context = {"patient_list": all_patients}
    return render(request, "uploader/index.html", context)


def patient_data(request, patient_id):
    patient = get_object_or_404(Patient, pk=patient_id)
    context = {"patient": patient,
               "patient_fields": patient._meta.fields
               }

    return render(request, "uploader/patients.html", context)


def samples(request, patient_id):
    data = get_object_or_404(Patient, pk=patient_id).data
    return HttpResponse(f"Bios sample data for patient '{patient_id}': {data}.")
