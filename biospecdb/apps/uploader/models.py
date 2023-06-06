from enum import StrEnum, auto
import uuid

from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models

# Changes here need to be migrated, committed, and activated.
# See https://docs.djangoproject.com/en/4.2/intro/tutorial02/#activating-models
# python manage.py makemigrations uploader
# git add biospecdb/apps/uploader/migrations
# git commit -asm"Update uploader model(s)"
# python manage.py migrate
# python manage.py sqlmigrate uploader <migration_version>

POSITIVE = "positive"
NEGATIVE = "negative"


class Patient(models.Model):
    MIN_AGE = 0
    MAX_AGE = 150

    class Gender(StrEnum):
        MALE = auto()
        FEMALE = auto()
        # NA = auto()  # ?

    patient_id = models.UUIDFIELD(unique=True, primary_key=True, default=uuid.uuid4, editable=False)
    gender = models.CharField(max_length=1, choices=Gender)


class BaseJSONType:
    def to_dict(self):
        return vars(self)


class Symptom(BaseJSONType):
    def __int__(self, name: str, symptomatic: bool, duration: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name
        self.symptomatic = symptomatic
        self.duration = duration  # days


class SymptomField(models.JSONField):
    # TODO: Abstract most of this to base field class.

    class Creator:
        def __init__(self, field):
            self.field = field

        def __get__(self, obj):
            if obj is None:
                return self

            return obj.__dict__(self.field.name)

        def __set__(self, obj, value):
            obj.__dict__[self.field.name] = self.convert_input(value)

        def convert_input(self, value):
            if value is None:
                return None

            if isinstance(value, Symptom):
                return value
            else:
                return Symptom(**value)

    def from_db_value(self, value, expression, connection):
        db_val = super().from_db_value(value, expression, connection)

        if db_val is None:
            return db_val

        return Symptom(**db_val)

    def get_prep_value(self, value):
        dict_value = value.to_dict()
        prep_value = super().get_prep_value(dict_value)
        return prep_value

    def contribute_to_class(self, cls, name, private_only=False):
        super().contribute_to_class(cls, name, private_only=private_only)
        setattr(cls, self.name, self.Creator(self))


class Symptoms(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="symptoms")
    patient_age = models.IntegerField(validators=[MinValueValidator(Patient.MIN_AGE),
                                                  MaxValueValidator(Patient.MAX_AGE)])

    # moved to BaseSymptom
    # days_of_symptoms = models.IntegerField(default=0, null=True)  # DurationField?

    # SARS-CoV-2 (COVID) viral load indicators.
    Ct_gene_N = models.FloatField()
    Ct_gene_ORF1ab = models.FloatField()
    Covid_RT_qPCR = models.CharField(default=NEGATIVE, choices=(NEGATIVE, POSITIVE))

    # Symptoms/Diseases
    fever = SymptomField(default=False)
    dyspnoea = SymptomField(default=False)
    oxygen_saturation_lt_95 = SymptomField(default=False)
    cough = SymptomField(default=False)
    coryza = SymptomField(default=False)
    odinophagy = SymptomField(default=False)
    diarrhea = SymptomField(default=False)
    nausea = SymptomField(default=False)
    headache = SymptomField(default=False)
    weakness = SymptomField(default=False)
    anosmia = SymptomField(default=False)
    myalgia = SymptomField(default=False)
    no_appetite = SymptomField(default=False)
    vomiting = SymptomField(default=False)
    suspicious_contact = SymptomField(default=False)
    chronic_pulmonary_inc_asthma = SymptomField(default=False)
    cardiovascular_disease_inc_hypertension = SymptomField(default=False)
    diabetes = SymptomField(default=False)
    chronic_or_neuromuscular_neurological_disease = SymptomField(default=False)

    more = SymptomListField()  # TODO: Write this.


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
    # SET_NULL | CASCADE?
    symptoms = models.ForeignKey(Symptoms, null=True, on_delete=models.SET_NULL, related_name="samples")

    # Sample meta.
    sample_type = models.CharField(default=SampleKind.PHARYNGEAL_SWAB, max_length=128, choices=SampleKind)
    sample_processing = models.CharField(default="None", max_length=128)
    freezing_time = models.IntegerField(blank=True, null=True)
    thawing_time = models.IntegerField(blank=True, null=True)

    # Spectrometer meta.
    spectra_measurement = models.CharField(default=SpectralMeasurementKind.ATR_FTIR, max_length=128,
                                           choices=SpectralMeasurementKind)
    spectrometer = models.CharField(default=Spectrometers.AGILENT_COREY_630, max_length=128, choices=Spectrometers)
    atr_crystal = models.CharField(default=SpectrometerCrystal.ZNSE, max_length=128, choices=SpectrometerCrystal)
    acquisition_time = models.IntegerField(blank=True, null=True)
    n_coadditions = models.IntegerField(default=32)
    resolution = models.IntegerField(blank=True, null=True)

    qc_metrics = models.JSONField()

    # Spectral data.
    # TODO: We could write a custom storage class to write these all to a parquet table instead of individual files.
    # See https://docs.djangoproject.com/en/4.2/howto/custom-file-storage/
    data = models.FileField(upload_to="uploads/")
