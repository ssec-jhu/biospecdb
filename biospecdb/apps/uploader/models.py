from enum import StrEnum, auto
import uuid

from django.contrib.postgres.fields import ArrayField, HStoreField
from django.db import models

# Changes here need to be migrated, committed, and activated.
# See https://docs.djangoproject.com/en/4.2/intro/tutorial02/#activating-models
# python manage.py makemigrations uploader
# git add biospecdb/apps/uploader/migrations
# git commit -asm"Update uploader model(s)"
# python manage.py migrate
# python manage.py sqlmigrate uploader <migration_version>


class Patient(models.Model):
    class Gender(StrEnum):
        MALE = auto()
        FEMALE = auto()
        # NA = auto()  # ?

    patient_id = models.UUIDFIELD(unique=True, primary_key=True, default=uuid.uuid4, editable=False)
    gender = models.CharField(max_length=1, choices=Gender)


class Symptoms(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="symptoms")

    age = models.IntegerField()
    days_of_symptoms = models.IntegerField(default=0)  # DurationField?

    # Symptoms/Diseases
    fever = models.BooleanField(default=False)
    dyspnoea = models.BooleanField(default=False)
    oxygen_saturation_lt_95 = models.BooleanField(default=False)
    cough = models.BooleanField(default=False)
    coryza = models.BooleanField(default=False)
    odinophagy = models.BooleanField(default=False)
    diarrhea = models.BooleanField(default=False)
    nausea = models.BooleanField(default=False)
    headache = models.BooleanField(default=False)
    weakness = models.BooleanField(default=False)
    anosmia = models.BooleanField(default=False)
    myalgia = models.BooleanField(default=False)
    no_appetite = models.BooleanField(default=False)
    vomiting = models.BooleanField(default=False)
    suspicious_contact = models.BooleanField(default=False)
    chronic_pulmonary_inc_asthma = models.BooleanField(default=False)
    cardiovascular_disease_inc_hypertension = models.BooleanField(default=False)
    diabetes = models.BooleanField(default=False)
    chronic_or_neuromuscular_neurological_disease = models.BooleanField(default=False)

    more = HStoreField()


class BioSample(models.Model):
    class Spectrometers(StrEnum):
        AGILENT_COREY_630 = auto()

    class SpectralMeasurementKind(StrEnum):
        ATR_FTIR = auto()

    class SampleKind(StrEnum):
        PHARYNGEAL_SWAB = auto()

    class SpectrometerCrystal(StrEnum):
        ZNSE = auto()

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="samples")
    symptoms = models.ForeignKey(Symptoms, null=True, on_delete=models.SET_NULL, related_name="samples")  # SET_NULL | CASCADE?

    # Sample meta.
    sample_type = models.CharField(default=SampleKind.PHARYNGEAL_SWAB, max_length=128, choices=SampleKind)
    sample_processing = models.CharField(default="None", max_length=128)
    freezing_time = models.IntegerField(blank=True, null=True)
    thawing_time = models.IntegerField(blank=True, null=True)

    # Spectrometer meta.
    spectra_measurement = models.CharField(default=SpectralMeasurementKind.ATR_FTIR, max_length=128, choices=SpectralMeasurementKind)
    spectrometer = models.CharField(default=Spectrometers.AGILENT_COREY_630, max_length=128, choices=Spectrometers)
    atr_crystal = models.CharField(default=SpectrometerCrystal.ZNSE, max_length=128, choices=SpectrometerCrystal)
    acquisition_time = models.IntegerField(blank=True, null=True)
    n_coadditions = models.IntegerField(default=32)
    resolution = models.IntegerField(blank=True, null=True)

    # Spectral data.
    wavelengths = ArrayField(models.FloatField())
    intensities = ArrayField(models.FloatField())
