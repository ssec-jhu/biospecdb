from copy import deepcopy
from enum import auto
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator, MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
import pandas as pd

import biospecdb.util
from biospecdb.qc.qcfilter import QcFilter
from uploader.loaddata import save_data_to_db
from uploader.sql import secure_name
from uploader.base_models import ModelWithViewDependency, SqlView, TextChoices, Types


# Changes here need to be migrated, committed, and activated.
# See https://docs.djangoproject.com/en/4.2/intro/tutorial02/#activating-models
# python manage.py makemigrations uploader
# git add biospecdb/apps/uploader/migrations
# git commit -asm"Update uploader model(s)"
# python manage.py migrate
# python manage.py sqlmigrate uploader <migration_version>

POSITIVE = "positive"
NEGATIVE = "negative"

# https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html
# NOTE: Examples of PHI:
# Medical record number.
# Health plan beneficiary number.
# Device identifiers or serial numbers.
# An MRI scan.
# Blood test results.
# Any other unique identifying numbers, characteristics, or codes.

# The following PII is considered PHI when accompanied by health data (i.e., as it would be for this project).
# Name.
# Address (including subdivisions smaller than state such as street address, city, county, or zip code).
# All elements of dates (except year) for dates that are directly related to an individual, including birth date,
# admission date, discharge date, death date, and all ages over 89 and all elements of dates (including year)
# indicative of such age, except that such ages and elements may be aggregated into a single category of age 90 or
# older.
# Telephone number.
# Fax number.
# Email address.
# Social Security number.
# Social Security number.
# Account number.
# Certificate/license number.
# Vehicle identifiers, serial numbers, or license plate numbers.
# Web URLs.
# IP address.
# Biometric identifiers such as fingerprints or voice prints.
# Full-face photos.
# Any other unique identifying numbers, characteristics, or codes.


class UploadedFile(models.Model):
    FileFormats = biospecdb.util.FileFormats
    UPLOAD_DIR = "raw_data/"  # MEDIA_ROOT/raw_data

    meta_data_file = models.FileField(upload_to=UPLOAD_DIR,
                                      validators=[FileExtensionValidator(biospecdb.util.FileFormats.choices())],
                                      help_text="File containing rows of all patient, symptom, and other meta data.")
    spectral_data_file = models.FileField(upload_to=UPLOAD_DIR,
                                          validators=[FileExtensionValidator(biospecdb.util.FileFormats.choices())],
                                          help_text="File containing rows of spectral intensities for the corresponding"
                                                    " meta data file.")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    @staticmethod
    def validate_lengths(meta_data, spec_data):
        """ Validate that files must be of equal length (same number of rows). """
        if len(meta_data) != len(spec_data):
            raise ValidationError(_("meta and spectral data must be of equal length (%(a)i!=%(b)i)."),
                                  params={"a": len(meta_data), "b": len(spec_data)},
                                  code="invalid")

    @staticmethod
    def join_with_validation(meta_data, spec_data):
        """ Validate primary keys are unique and associative. """

        if not meta_data.index.equals(spec_data.index):
            raise ValidationError(_("Patient ID mismatch. IDs from %(a)s must exactly match all those from %(b)s"),
                                  params=dict(a=UploadedFile.meta_data_file.field.name,
                                              b=UploadedFile.spectral_data_file.field.name),
                                  code="invalid")

        try:
            # The simplest way to do this is to utilize pandas.DataFrame.join().
            return meta_data.join(spec_data, how="left", validate="1:1")  # Might as well return the join.
        except pd.errors.MergeError as error:
            raise ValidationError(_("meta and spectral data must have unique and identical patient IDs")) from error

    def clean(self):
        """ Model validation. """

        super().clean()

        # Read in all data.
        # Note: When accessing ``models.FileField`` Django returns ``models.FieldFile`` as a proxy.
        meta_data = biospecdb.util.read_meta_data(*biospecdb.util.get_file_info(self.meta_data_file.file))
        spec_data = biospecdb.util.read_spectral_data_table(*biospecdb.util.get_file_info(self.spectral_data_file.file))
        # Validate.
        UploadedFile.validate_lengths(meta_data, spec_data)
        # This uses a join so returns the joined data so that it doesn't go to waste if needed, which it is here.
        joined_data = UploadedFile.join_with_validation(meta_data, spec_data)

        # Ingest into DB.
        save_data_to_db(None, None, joined_data=joined_data)


class Patient(models.Model):
    """ Model an individual patient. """
    MIN_AGE = 0
    MAX_AGE = 150  # NOTE: HIPAA requires a max age of 90 to be stored. However, this is GDPR data so... :shrug:

    class Gender(TextChoices):
        MALE = ("M", _("Male"))  # NOTE: Here variation here act as aliases for bulk column ingestion.
        FEMALE = ("F", _("Female"))  # NOTE: Here variation here act as aliases for bulk column ingestion.

    patient_id = models.UUIDField(unique=True,
                                  primary_key=True,
                                  default=uuid.uuid4,
                                  verbose_name="Patient ID")
    gender = models.CharField(max_length=8, choices=Gender.choices, null=True, verbose_name="Gender (M/F)")

    def __str__(self):
        return str(self.patient_id)

    def short_id(self):
        return str(self.patient_id)[:8]


class Visit(models.Model):
    """ Model a patient's visitation to collect health data and biological samples.  """

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="visit")

    # NOTE: This has to allow for blank to accommodate the initial vist for which there is no prior.
    previous_visit = models.ForeignKey("self", default=None, blank=True, null=True, on_delete=models.SET_NULL,
                                       related_name="next_visit")

    patient_age = models.IntegerField(validators=[MinValueValidator(Patient.MIN_AGE),
                                                  MaxValueValidator(Patient.MAX_AGE)],
                                      verbose_name="Age")

    def clean(self):
        """ Model validation. """
        super().clean()

        # Validate that previous visit isn't this visit.
        if self.previous_visit is not None and (self.previous_visit.pk == self.pk):
            raise ValidationError(_("Previous visit cannot not be this current visit"))

        # Validate visits belong to same patient.
        if self.previous_visit is not None and (self.previous_visit.patient_id != self.patient_id):
            raise ValidationError(_("Previous visits do not belong to this patient!"), code="invalid")

        # Validate visits are entered ordered by age.
        if self.previous_visit is not None and (self.patient_age < self.previous_visit.patient_age):
            raise ValidationError(_("Previous visit must NOT be older than this one: patient age before %(prior_age)i "
                                    " > %(current_age)i"),
                                  params={"current_age": self.patient_age,
                                          "prior_age": self.previous_visit.patient_age},
                                  code="invalid")

    def count_prior_visits(self):
        return 0 if self.previous_visit is None else 1 + self.previous_visit.count_prior_visits()

    @property
    def visit_number(self):
        return 1 + self.count_prior_visits()

    def __str__(self):
        return f"patient:{self.patient.short_id()}_visit:{self.visit_number}"


class Disease(ModelWithViewDependency):
    """ Model an individual disease, symptom, or health condition. A patient's instance are stored as models.Symptom"""

    Types = Types

    sql_view_dependencies = ("uploader.models.VisitSymptomsView",)

    class Meta:
        constraints = [models.UniqueConstraint(Lower("name"),
                                               name="unique_disease_name"),
                       models.UniqueConstraint(Lower("alias"),
                                               name="unique_alias_name")]

    # NOTE: See above constraint for case-insensitive uniqueness.
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=256)

    # NOTE: See meta class constraint for case-insensitive uniqueness.
    alias = models.CharField(max_length=128,
                             help_text="Alias column name for bulk data ingestion from .csv, etc.")

    # This represents the type/class for Symptom.disease_value.
    value_class = models.CharField(max_length=128, default=Types.BOOL, choices=Types.choices)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if not self.alias:
            self.alias = self.name.replace('_', ' ')


class Symptom(models.Model):
    """ A patient's instance of models.Disease. """
    MIN_SEVERITY = 0
    MAX_SEVERITY = 10

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="symptom")
    disease = models.ForeignKey(Disease, on_delete=models.CASCADE, related_name="symptom")

    days_symptomatic = models.IntegerField(default=None,
                                           blank=True,
                                           null=True,
                                           validators=[MinValueValidator(0)],
                                           verbose_name="Days of Symptoms onset")
    severity = models.IntegerField(default=None,
                                   validators=[MinValueValidator(MIN_SEVERITY),
                                                             MaxValueValidator(MAX_SEVERITY)],
                                   blank=True,
                                   null=True)

    # Str format for actual type/class spec'd by Disease.value_class.
    disease_value = models.CharField(blank=True, null=True, default='', max_length=128)

    def clean(self):
        """ Model validation. """
        super().clean()

        # Check that value is castable by casting.
        # NOTE: ``disease_value`` is a ``CharField`` so this will get cast back to a str again, and it could be argued
        # that there's no point in storing the cast value... but :shrug:.
        try:
            self.disease_value = Disease.Types(self.disease.value_class).cast(self.disease_value)
        except ValueError:
            raise ValidationError(_("The value '%(value)s' can not be cast to the expected type of '%(type)s' for"
                                    " '%(disease_name)s'"),
                                  params={"disease_name": self.disease.name,
                                          "type": self.disease.value_class,
                                          "value": self.disease_value},
                                  code="invalid")

        if self.days_symptomatic and self.visit.patient_age and (self.days_symptomatic >
                                                                 (self.visit.patient_age * 365)):
            raise ValidationError(_("The field `days_symptomatic` can't be greater than the patients age (in days):"
                                    " %(days_symptomatic)i > %(age)i"),
                                  params={"days_symptomatic": self.days_symptomatic,
                                          "age": self.visit.patient_age * 365},
                                  code="invalid")

    def __str__(self):
        return f"patient:{self.visit.patient.short_id()}_{self.disease.name}"


class Instrument(models.Model):
    """ Model the instrument/device used to measure spectral data (not the collection of the bio sample). """

    class Spectrometers(TextChoices):
        AGILENT_CORY_630 = auto()

    class SpectrometerCrystal(TextChoices):
        ZNSE = auto()

    class Meta:
        unique_together = [["spectrometer", "atr_crystal"]]

    spectrometer = models.CharField(default=Spectrometers.AGILENT_CORY_630,
                                    max_length=128,
                                    choices=Spectrometers.choices,
                                    verbose_name="Spectrometer")
    atr_crystal = models.CharField(default=SpectrometerCrystal.ZNSE,
                                   max_length=128,
                                   choices=SpectrometerCrystal.choices,
                                   verbose_name="ATR Crystal")

    def __str__(self):
        return self.spectrometer


class BioSample(models.Model):
    """ Model biological sample and collection method. """
    class SampleKind(TextChoices):
        PHARYNGEAL_SWAB = auto()

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="bio_sample")

    # Sample meta.
    sample_type = models.CharField(max_length=128,
                                   choices=SampleKind.choices,
                                   verbose_name="Sample Type")
    sample_processing = models.CharField(default="None",
                                         blank=True,
                                         null=True,
                                         max_length=128,
                                         verbose_name="Sample Processing")
    freezing_temp = models.FloatField(blank=True, null=True, verbose_name="Freezing Temperature")
    thawing_time = models.IntegerField(blank=True, null=True, verbose_name="Thawing time")

    def __str__(self):
        return f"{self.visit}_type:{self.sample_type}_pk{self.pk}"  # NOTE: str(self.visit) contains patient ID.


class SpectralData(models.Model):
    """ Model spectral data measured by spectrometer instrument. """

    class Meta:
        verbose_name = "Spectral Data"
        verbose_name_plural = verbose_name

    UPLOAD_DIR = "spectral_data/"  # MEDIA_ROOT/spectral_data

    class SpectralMeasurementKind(TextChoices):
        ATR_FTIR = auto()

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="spectral_data")
    bio_sample = models.ForeignKey(BioSample, on_delete=models.CASCADE, related_name="spectral_data")

    # Spectrometer meta.
    spectra_measurement = models.CharField(default=SpectralMeasurementKind.ATR_FTIR,
                                           max_length=128,
                                           choices=SpectralMeasurementKind.choices,
                                           verbose_name="Spectra Measurement")
    acquisition_time = models.IntegerField(blank=True, null=True, verbose_name="Acquisition time [s]")

    # TODO: What is this? Could this belong to Instrument?
    n_coadditions = models.IntegerField(default=32, verbose_name="Number of coadditions")

    resolution = models.IntegerField(blank=True, null=True, verbose_name="Resolution [cm-1]")

    # Spectral data.
    # TODO: We could write a custom storage class to write these all to a parquet table instead of individual files.
    # See https://docs.djangoproject.com/en/4.2/howto/custom-file-storage/
    data = models.FileField(upload_to=UPLOAD_DIR,
                            validators=[FileExtensionValidator(UploadedFile.FileFormats.choices())],
                            verbose_name="Spectral data file")

    def __str__(self):
        return f"{self.bio_sample.visit}_pk{self.pk}"

    def get_annotators(self):
        return list(set([annotation.annotator for annotation in self.qc_annotation.all()]))

    def get_unrun_annotators(self, existing_annotators=None):
        # Get annotators from existing annotations.
        if existing_annotators is None:
            existing_annotators = self.get_annotators()

        # Some default annotators may not have been run yet (newly added), so check.
        all_default_annotators = QCAnnotator.objects.filter(default=True)

        return list(set(all_default_annotators) - set(existing_annotators))

    def get_spectral_df(self):
        data_file, ext = biospecdb.util.get_file_info(self.data)
        data, patient_id = biospecdb.util.read_individual_spectral_data(data_file, ext=ext)
        return data, patient_id,

    #@transaction.atomic  # Really? Not sure if this even can be if run in background...
    # See https://github.com/ssec-jhu/biospecdb/issues/77
    def annotate(self, annotator=None, force=False) -> list:
        # TODO: This needs to return early and run in the background.
        # See https://github.com/ssec-jhu/biospecdb/issues/77

        existing_annotators = self.get_annotators()

        # Run only the provided annotator.
        if annotator:
            if annotator in existing_annotators:
                if not force:
                    return
                annotation = self.qc_annotation.get(annotator=annotator)
            else:
                annotation = QCAnnotation(annotator=annotator, spectral_data=self)
            return [annotation.run()]

        annotations = []
        # Rerun existing annotations.
        if force and existing_annotators:
            for annotation in self.qc_annotation.all():
                annotations.append(annotation.run())

        new_annotators = self.get_unrun_annotators(existing_annotators=existing_annotators)

        # Create new annotations.
        for annotator in new_annotators:
            annotation = QCAnnotation(annotator=annotator, spectral_data=self)
            annotations.append(annotation.run())

        return annotations if annotations else None  # Don't ret empty list.

    def clean(self):
        """ Model validation. """
        super().clean()

        # Check patient ID in supplied data file is correct.
        expected_patient_id = self.bio_sample.visit.patient.patient_id
        _data, patient_id_from_file = self.get_spectral_df()
        if patient_id_from_file != expected_patient_id:
            raise ValidationError(_("Patient IDs don't match! Can't add spectral data for patient: '%(a)s' to"
                                    "patient '%(b)s'"),
                                  params=dict(a=expected_patient_id, b=patient_id_from_file),
                                  code="invalid")

        # Compute QC metrics.
        # TODO: Even with the QC model being its own thing rather than fields here, we may still want to run here
        # such that new data is complete such that it has associated QC metrics.
        if settings.AUTO_ANNOTATE:
            # TODO: This should return early and runs async in the background.
            # See https://github.com/ssec-jhu/biospecdb/issues/77
            self.annotate()


class SymptomsView(SqlView, models.Model):
    class Meta:
        managed = False
        db_table = "v_symptoms"

    visit_id = models.BigIntegerField(primary_key=True)
    symptom_id = models.ForeignKey(Symptom, db_column="symptom_id", on_delete=models.DO_NOTHING)
    disease_id = models.ForeignKey(Disease, db_column="disease_id", on_delete=models.DO_NOTHING)
    disease = deepcopy(Disease.name.field)
    disease.name = disease.db_column = "disease"
    value_class = deepcopy(Disease.value_class.field)
    days_symptomatic = deepcopy(Symptom.days_symptomatic.field)
    severity = deepcopy(Symptom.severity.field)
    disease_value = deepcopy(Symptom.disease_value.field)

    @classmethod
    def sql(cls):
        sql = f"""
        CREATE VIEW {cls._meta.db_table} AS
        SELECT s.visit_id,
               s.id AS symptom_id,
               d.id AS disease_id,
               d.name AS disease,
               d.value_class,
               s.days_symptomatic,
               s.severity,
               s.disease_value
        FROM uploader_symptom s
        JOIN uploader_disease d ON d.id=s.disease_id
        """  # nosec B608
        return sql, None


class VisitSymptomsView(SqlView, models.Model):
    class Meta:
        managed = False
        db_table = "v_visit_symptoms"

    sql_view_dependencies = (SymptomsView,)

    visit_id = models.BigIntegerField(primary_key=True)

    @classmethod
    def sql(cls):
        diseases = Disease.objects.all()
        view = cls._meta.db_table
        d = []
        for disease in diseases:
            secure_name(disease.name)
            if disease.value_class == "FLOAT":
                value = 'cast(disease_value AS REAL)'
            elif disease.value_class == "INTEGER":
                value = "cast(disease_value AS INTEGER)"
            else:
                value = "disease_value"
            d.append(f"max(case when disease = '{disease.name}' then {value} else null end) as [{disease.name}]")

        d = "\n,      ".join(d)

        # NOTE: Params aren't allowed in view statements with sqlite. Since disease can be added to the DB this poses
        # as a risk since someone with access to creating diseases could inject into disease.name arbitrary SQL. Calling
        # secure_name(disease.name) may not entirely guard against this even though its intention is to do so.
        sql = f"""
        create view {view} as
        select visit_id
        ,      {d} 
          from v_symptoms 
         group by visit_id
        """  # nosec B608

        return sql, None


class FullPatientView(SqlView, models.Model):
    class Meta:
        managed = False
        db_table = "full_patient"

    sql_view_dependencies = (VisitSymptomsView,)

    @classmethod
    def sql(cls):
        sql = f"""
                create view {cls._meta.db_table} as 
                select p.patient_id, p.gender, v.patient_age
                ,      bs.sample_type, bs.sample_processing, bs.freezing_temp, bs.thawing_time
                ,      i.spectrometer, i.atr_crystal
                ,      sd.spectra_measurement, sd.acquisition_time, sd.n_coadditions, sd.resolution, sd.data
                ,      vs.*
                  from uploader_patient p
                  join uploader_visit v on p.patient_id=v.patient_id
                  join uploader_biosample bs on bs.visit_id=v.id
                  join uploader_spectraldata sd on sd.bio_sample_id=bs.id
                  join uploader_instrument i on i.id=sd.instrument_id
                  left outer join v_visit_symptoms vs on vs.visit_id=v.id
                """  # nosec B608
        return sql, None


def validate_qc_annotator_import(value):
    try:
        obj = import_string(value)
    except ImportError:
        raise ValidationError(_("'%(a)s' cannot be imported. Server re-deployment may be required."
                                " Please reach out to the server admin."),
                              params=dict(a=value),
                              code="invalid")

    if obj and not issubclass(obj, QcFilter):  # NOTE: issubclass is used since QcFilter is abstract.
        raise ValidationError(_("fully_qualified_class_name must be of type %(a)s not"
                                "'%(b)s'"),
                              params=dict(a=type(obj), b=QcFilter.__qualname__),
                              code="invalid")


class QCAnnotator(models.Model):
    Types = Types

    name = models.CharField(max_length=128, unique=True, blank=False, null=False)
    fully_qualified_class_name = models.CharField(max_length=128,
                                                  blank=False,
                                                  null=False,
                                                  unique=True,
                                                  help_text="This must be the fully qualified Python name for an"
                                                            " implementation of QCFilter, e.g.,"
                                                            "'myProject.qc.myQCFilter'.",
                                                  validators=[validate_qc_annotator_import])
    value_type = models.CharField(blank=False, null=False, max_length=128, default=Types.BOOL, choices=Types.choices)
    description = models.CharField(blank=True, null=True, max_length=256)
    default = models.BooleanField(default=True,
                                  blank=False,
                                  null=False,
                                  help_text="If True it will apply to all spectral data samples.")

    def __str__(self):
        return f"{self.name}: {self.fully_qualified_class_name}"

    def cast(self, value):
        if value:
            return self.Types(self.value_type).cast(value)

    def run(self, *args, **kwargs):
        obj = import_string(self.fully_qualified_class_name)
        return obj.run(obj, *args, **kwargs)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        if settings.RUN_DEFAULT_ANNOTATORS_WHEN_SAVED and self.default:
            # Run annotator on all spectral data samples.
            for data in SpectralData.objects.all():
                # Since this annotator could have been altered (from django) rather than being new, annotations
                # of this annotator may already exist, thus we need to force them to be re-run.
                data.annotate(annotator=self, force=True)


class QCAnnotation(models.Model):

    class Meta:
        unique_together = [["annotator", "spectral_data"]]

    value = models.CharField(blank=True, null=True, max_length=128)

    annotator = models.ForeignKey(QCAnnotator,
                                  blank=False,
                                  null=False,
                                  on_delete=models.CASCADE,
                                  related_name="qc_annotation")
    spectral_data = models.ForeignKey(SpectralData, on_delete=models.CASCADE, related_name="qc_annotation")

    def __str__(self):
        return f"{self.annotator.name}: {self.value}"

    def get_value(self):
        if self.annotator:
            return self.annotator.cast(self.value)

    def run(self, save=True):
        # NOTE: This waits. See https://github.com/ssec-jhu/biospecdb/issues/77
        value = self.annotator.run(self.spectral_data)
        self.value = value

        if save:
            self.save()

        return self.value

    def clean(self):
        super().clean()
        self.run()


# This is Model B wo/ disease table https://miro.com/app/board/uXjVMAAlj9Y=/
# class Symptoms(models.Model):
#     visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="symptoms")
#
#     # SARS-CoV-2 (COVID) viral load indicators.
#     Ct_gene_N = models.FloatField()
#     Ct_gene_ORF1ab = models.FloatField()
#     Covid_RT_qPCR = models.CharField(default=NEGATIVE, choices=(NEGATIVE, POSITIVE))
#     suspicious_contact = models.BooleanField(default=False)
#
#     # Symptoms/Diseases
#     fever = models.BooleanField(default=False)
#     dyspnoea = models.BooleanField(default=False)
#     oxygen_saturation_lt_95 = models.BooleanField(default=False)
#     cough = models.BooleanField(default=False)
#     coryza = models.BooleanField(default=False)
#     odinophagy = models.BooleanField(default=False)
#     diarrhea = models.BooleanField(default=False)
#     nausea = models.BooleanField(default=False)
#     headache = models.BooleanField(default=False)
#     weakness = models.BooleanField(default=False)
#     anosmia = models.BooleanField(default=False)
#     myalgia = models.BooleanField(default=False)
#     no_appetite = models.BooleanField(default=False)
#     vomiting = models.BooleanField(default=False)
#     chronic_pulmonary_inc_asthma = models.BooleanField(default=False)
#     cardiovascular_disease_inc_hypertension = models.BooleanField(default=False)
#     diabetes = models.BooleanField(default=False)
#     chronic_or_neuromuscular_neurological_disease = models.BooleanField(default=False)
#
#     more = models.JSONField()
