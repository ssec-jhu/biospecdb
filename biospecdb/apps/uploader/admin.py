from django.contrib import admin

from uploader.models import Patient, BioSample

admin.site.register(Patient)
admin.site.register(BioSample)
