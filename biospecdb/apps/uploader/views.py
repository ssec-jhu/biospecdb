from django.http import HttpResponse

from uploader.models import Patient


def index(request):
    return HttpResponse("Hello, world. You're at the uploader index.")


def patients(request, patient_id):
    meta = Patient.objects.get(patient_id=patient_id)
    return HttpResponse(f"Meta data for patient '{patient_id}': {meta}.")


def samples(request, patient_id):
    data = Patient.objects.get(patient_id=patient_id).data
    return HttpResponse(f"Bios sample data for patient '{patient_id}': {data}.")
