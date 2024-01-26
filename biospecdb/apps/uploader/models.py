from collections import Counter
from copy import deepcopy
from enum import auto
import os
from pathlib import Path
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import FileExtensionValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _
import pandas as pd

from biospecdb.util import get_field_value, get_object_or_raise_validation, is_valid_uuid, lower, to_uuid
from biospecdb.qc.qcfilter import QcFilter
import uploader.io
from uploader.loaddata import save_data_to_db
from uploader.sql import secure_name
from uploader.base_models import DatedModel, ModelWithViewDependency, SqlView, TextChoices, Types
from user.models import BaseCenter as UserBaseCenter

# Changes here need to be migrated, committed, and activated.
# See https://docs.djangoproject.com/en/4.2/intro/tutorial02/#activating-models
# python manage.py makemigrations uploader
# git add biospecdb/apps/uploader/migrations
# git commit -asm"Update uploader model(s)"
# python manage.py migrate --database=bsr

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


class Center(UserBaseCenter):
    ...


class UploadedFile(DatedModel):
    class Meta:
        verbose_name = "Bulk Data Upload"
        get_latest_by = "updated_at"

    FileFormats = uploader.io.FileFormats
    UPLOAD_DIR = "raw_data/"  # MEDIA_ROOT/raw_data

    meta_data_file = models.FileField(upload_to=UPLOAD_DIR,
                                      validators=[FileExtensionValidator(uploader.io.FileFormats.choices())],
                                      help_text="File containing rows of all patient, observation, and other meta"
                                                " data.")
    spectral_data_file = models.FileField(upload_to=UPLOAD_DIR,
                                          validators=[FileExtensionValidator(uploader.io.FileFormats.choices())],
                                          help_text="File containing rows of spectral intensities for the corresponding"
                                                    " meta data file.")
    center = models.ForeignKey(Center, null=False, blank=False, on_delete=models.PROTECT)

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

    def _validate_and_save_data_to_db(self, dry_run=False):
        # Read in all data.
        # Note: When accessing ``models.FileField`` Django returns ``models.FieldFile`` as a proxy.
        meta_data = uploader.io.read_meta_data(self.meta_data_file.file)
        spec_data = uploader.io.read_spectral_data_table(self.spectral_data_file.file)
        # Validate.
        UploadedFile.validate_lengths(meta_data, spec_data)
        # This uses a join so returns the joined data so that it doesn't go to waste if needed, which it is here.
        joined_data = UploadedFile.join_with_validation(meta_data, spec_data)

        # Ingest into DB.
        save_data_to_db(None, None, center=self.center, joined_data=joined_data, dry_run=dry_run, src_file=self)

    def clean(self):
        """ Model validation. """
        super().clean()
        self._validate_and_save_data_to_db(dry_run=True)

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._validate_and_save_data_to_db(dry_run=False)

    def asave(self, *args, **kwargs):
        raise NotImplementedError

    def delete(self, *args, **kwargs):
        """ Delete uploaded bulk data file AND conditionally all associated DB entries. """

        # Collect these now as they aren't accessible post deletion.
        visits = self.visits.all() if settings.DELETE_VISITS_WHEN_DELETING_BULK_UPLOAD else None

        count, deleted = super().delete(*args, **kwargs)
        if count == 1:
            os.remove(self.meta_data_file.name)
            os.remove(self.spectral_data_file.name)

            if settings.DELETE_VISITS_WHEN_DELETING_BULK_UPLOAD:
                for visit in visits:
                    spectral_data = [x for bio_sample in visit.bio_sample.all() for x in bio_sample.spectral_data.all()]

                    tmp_count, tmp_deleted = visit.delete()
                    count += tmp_count
                    deleted = dict(Counter(deleted) + Counter(tmp_deleted))

                    # Manually delete spectral_data files as the above visit.delete() happens at the DB layer thus
                    # not calling ``SpectralData.delete()``.
                    for data in spectral_data:
                        try:
                            SpectralData.objects.get(pk=data.pk)
                        except SpectralData.DoesNotExist:
                            # Only delete files where DB entry was successfully deleted.
                            os.remove(data.data.name)

        return count, deleted

    def adelete(self, *args, **kwargs):
        raise NotImplementedError


class Patient(DatedModel):
    """ Model an individual patient. """
    MIN_AGE = 0
    MAX_AGE = 150  # NOTE: HIPAA requires a max age of 90 to be stored. However, this is GDPR data so... :shrug:

    class Meta:
        unique_together = [["patient_cid", "center"]]
        get_latest_by = "updated_at"

    class Gender(TextChoices):
        UNSPECIFIED = ("X", _("Unspecified"))  # NOTE: Here variation here act as aliases for bulk column ingestion.
        MALE = ("M", _("Male"))  # NOTE: Here variation here act as aliases for bulk column ingestion.
        FEMALE = ("F", _("Female"))  # NOTE: Here variation here act as aliases for bulk column ingestion.

    patient_id = models.UUIDField(unique=True,
                                  primary_key=True,
                                  default=uuid.uuid4,
                                  verbose_name="Patient ID")
    gender = models.CharField(max_length=8, choices=Gender.choices, null=True, verbose_name="Gender (M/F)")
    patient_cid = models.CharField(max_length=128,
                                   null=True,
                                   blank=True,
                                   help_text="Patient ID prescribed by the associated center")
    center = models.ForeignKey(Center, null=False, blank=False, on_delete=models.PROTECT)

    @classmethod
    def parse_fields_from_pandas_series(cls, series):
        """ Parse the pandas series for field values returning a dict. """
        gender = get_field_value(series, cls, "gender")
        gender = cls.Gender(gender)
        return dict(gender=gender)

    def __str__(self):
        if self.patient_cid:
            return str(f"PCID:{self.patient_cid}")
        else:
            return str(f"PID:{self.patient_id}")

    def short_id(self):
        if self.patient_cid:
            return str(f"PCID:{str(self.patient_cid)[:8]}")
        else:
            return str(f"PID:{str(self.patient_id)[:8]}")

    def clean(self):
        super().clean()

        # Since patient_cid is only unique with the center, it cannot be the same as patient_id (Patient.pk) since that
        # is unique by itself and would thus prevent duplicate patient_cids across multiple centers.
        if is_valid_uuid(self.patient_cid) and (to_uuid(self.patient_cid) == self.patient_id):
            raise ValidationError(_("Patient ID and patient CID cannot be the same"))


class Visit(DatedModel):
    """ Model a patient's visitation to collect health data and biological samples.  """

    class Meta:
        get_latest_by = "updated_at"

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="visit")

    # NOTE: This has to allow for blank to accommodate the initial vist for which there is no prior.
    previous_visit = models.ForeignKey("self", default=None, blank=True, null=True, on_delete=models.SET_NULL,
                                       related_name="next_visit")

    days_observed = models.IntegerField(default=None,
                                        blank=True,
                                        null=True,
                                        validators=[MinValueValidator(0)],
                                        verbose_name="Days observed",
                                        help_text="Applies to all visit observations unless otherwise specified")

    src_file = models.ForeignKey(UploadedFile,
                                 default=None,
                                 blank=True,
                                 null=True,
                                 on_delete=models.SET_NULL,
                                 related_name="visits",
                                 verbose_name="Source bulk data file",
                                 help_text="Visit created from this bulk data file")

    @classmethod
    def parse_fields_from_pandas_series(cls, series):
        """ Parse the pandas series for field values returning a dict. """
        return dict(days_observed=get_field_value(series, cls, "days_observed"))

    def clean(self):
        """ Model validation. """
        super().clean()

        if settings.AUTO_FIND_PREVIOUS_VISIT and not self.previous_visit:
            last_visit, duplicates_exist = self.auto_find_previous_visit()
            if duplicates_exist:
                raise ValidationError(_("Auto previous visit ambiguity: multiple visits have the exact same"
                                        "'created_at' timestamp - '%(timestamp)s'"),
                                      params={"timestamp": last_visit.created_at})
            self.previous_visit = last_visit

        # Validate that previous visit isn't this visit.
        if self.previous_visit is not None and (self.previous_visit.pk == self.pk):
            raise ValidationError(_("Previous visit cannot not be this current visit"))

        # Validate visits belong to same patient.
        if self.previous_visit is not None and (self.previous_visit.patient_id != self.patient_id):
            raise ValidationError(_("Previous visits do not belong to this patient!"), code="invalid")

        # Validate visits are entered ordered by age.
        if self.previous_visit is not None:
            try:
                patient_age = int(self.observation.get(observable__name="patient_age").observable_value)
            except Observation.DoesNotExist:
                pass
            else:
                try:
                    previous_visit_patient_age = int(self.previous_visit.observation.get(
                        observable__name="patient_age").observable_value)
                except Observation.DoesNotExist:
                    pass
                else:
                    if patient_age < previous_visit_patient_age:
                        raise ValidationError(_("Previous visit must NOT be older than this one: patient age before"
                                                "%(prior_age)i > %(current_age)i"),
                                              params={"current_age": patient_age,
                                                      "prior_age": previous_visit_patient_age},
                                              code="invalid")

    def auto_find_previous_visit(self):
        """ Find the previous visit.

            This is defined as the last visit with a ``created_at`` timestamp less than that of ``self.created_at``.
            WARNING! This may give incorrect results.
        """

        # New visits will not yet have a ``created_at`` entry as that happens upon save to the DB. In this case,
        # we could assume that save() is imminent and use the current time, i.e., ``datatime.datetime.now()``. However,
        # this seems sketchy, instead, it's safer to just not filter by creation timestamp since everything present
        # was added in the past. Note: Django fixture data could have future timestamps but that would be a curator bug.
        if self.created_at:
            previous_visits = Visit.objects.filter(patient_id=self.patient_id,
                                                   created_at__lt=self.created_at).order_by('created_at')
        else:
            previous_visits = Visit.objects.filter(patient_id=self.patient_id).order_by('created_at')

        if not previous_visits:
            return None, False

        last_visit = previous_visits.last()

        if last_visit == self:
            # This could be true when updating the only existing visit for a given patient, however, the above
            # filter(created_at__lt=self.created_at) would prevent this and shouldn't be possible otherwise. That being
            # said, we might as well make this more robust, just in case.
            return None, False

        # Is last visit unique?
        # TODO: Disambiguate using age and/or pk, and/or something else?
        duplicates_exist = previous_visits.filter(created_at=last_visit.created_at).count() > 1

        return last_visit, duplicates_exist

    def count_prior_visits(self):
        return 0 if self.previous_visit is None else 1 + self.previous_visit.count_prior_visits()

    @property
    def visit_number(self):
        return 1 + self.count_prior_visits()

    @property
    def center(self):
        return self.patient.center

    def __str__(self):
        return f"patient:{self.patient}_visit:{self.visit_number}"


class Observable(ModelWithViewDependency):
    """ Model an individual observable, observation, or health condition.
        A patient's instance are stored as models.Observation
    """

    class Category(TextChoices):
        BLOODWORK = auto()
        COMORBIDITY = auto()
        DRUG = auto()
        PATIENT_INFO = auto()
        PATIENT_INFO_II = auto()
        PATIENT_PREP = auto()
        SYMPTOM = auto()
        TEST = auto()
        VITALS = auto()

    Types = Types

    sql_view_dependencies = ("uploader.models.VisitObservationsView",)

    class Meta:
        get_latest_by = "updated_at"
        constraints = [models.UniqueConstraint(Lower("name"),
                                               name="unique_observable_name"),
                       models.UniqueConstraint(Lower("alias"),
                                               name="unique_alias_name")]

    category = models.CharField(max_length=128, null=False, blank=False, choices=Category.choices)
    # NOTE: See above constraint for case-insensitive uniqueness.
    name = models.CharField(max_length=128)
    description = models.CharField(max_length=256)

    # NOTE: See meta class constraint for case-insensitive uniqueness.
    alias = models.CharField(max_length=128,
                             help_text="Alias column name for bulk data ingestion from .csv, etc.")

    # This represents the type/class for Observation.observable_value.
    value_class = models.CharField(max_length=128, default=Types.BOOL, choices=Types.choices)

    # A observable without a center is generic and accessible by any and all centers.
    center = models.ForeignKey(Center, null=True, blank=True, on_delete=models.PROTECT)

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        if not self.alias:
            self.alias = self.name.replace('_', ' ')


class Observation(DatedModel):
    """ A patient's instance of models.Observable. """

    class Meta:
        get_latest_by = "updated_at"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="observation")
    observable = models.ForeignKey(Observable, on_delete=models.CASCADE, related_name="observation")

    days_observed = models.IntegerField(default=None,
                                        blank=True,
                                        null=True,
                                        validators=[MinValueValidator(0)],
                                        verbose_name="Days observed",
                                        help_text="Supersedes Visit.days_observed")

    # Str format for actual type/class spec'd by Observable.value_class.
    observable_value = models.CharField(blank=True, null=True, default='', max_length=128)

    def clean(self):
        """ Model validation. """
        super().clean()

        if self.observable.center and (self.observable.center != self.visit.patient.center):
            raise ValidationError(_("Patient observation observable category must belong to patient center: "
                                    "'%(c1)s' != '%(c2)s'"),
                                  params=dict(c1=self.observable.center, c2=self.visit.patient.center))

        # Check that value is castable by casting.
        # NOTE: ``observable_value`` is a ``CharField`` so this will get cast back to a str again, and it could be
        # argued that there's no point in storing the cast value... but :shrug:.
        try:
            self.observable_value = Observable.Types(self.observable.value_class).cast(self.observable_value)
        except ValueError:
            raise ValidationError(_("The value '%(value)s' can not be cast to the expected type of '%(type)s' for"
                                    " '%(observable_name)s'"),
                                  params={"observable_name": self.observable.name,
                                          "type": self.observable.value_class,
                                          "value": self.observable_value},
                                  code="invalid")

    @property
    def center(self):
        return self.visit.patient.center

    def __str__(self):
        return f"patient:{self.visit.patient.short_id()}_{self.observable.name}"


class Instrument(DatedModel):
    """ Model the instrument/device used to measure spectral data (not the collection of the bio sample). """

    class Meta:
        get_latest_by = "updated_at"

    # Instrument.
    id = models.UUIDField(unique=True, primary_key=True, default=uuid.uuid4)
    cid = models.CharField(max_length=128)
    manufacturer = models.CharField(max_length=128, verbose_name="Instrument manufacturer")
    model = models.CharField(max_length=128, verbose_name="Instrument model")
    serial_number = models.CharField(max_length=128, verbose_name="Instrument SN#")

    # Spectrometer.
    spectrometer_manufacturer = models.CharField(max_length=128, verbose_name="Spectrometer manufacturer")
    spectrometer_model = models.CharField(max_length=128, verbose_name="Spectrometer model")
    spectrometer_serial_number = models.CharField(max_length=128, verbose_name="Spectrometer SN#")

    # Laser.
    laser_manufacturer = models.CharField(max_length=128, verbose_name="Laser manufacturer")
    laser_model = models.CharField(max_length=128, verbose_name="Laser model")
    laser_serial_number = models.CharField(max_length=128, verbose_name="Laser SN#")

    center = models.ForeignKey(Center, null=True, blank=True, on_delete=models.PROTECT)

    @classmethod
    def parse_fields_from_pandas_series(cls, series):
        """ Parse the pandas series for field values returning a dict. """
        return dict(spectrometer__iexact=get_field_value(series, cls, "spectrometer"),
                    atr_crystal__iexact=get_field_value(series, cls, "atr_crystal"))

    def __str__(self):
        return f"{self.manufacturer}_{self.model}_{self.id}"


class BioSampleType(DatedModel):
    name = models.CharField(max_length=128, verbose_name="Sample Type")

    def __str__(self):
        return self.name


class BioSample(DatedModel):
    """ Model biological sample and collection method. """

    class Meta:
        get_latest_by = "updated_at"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="bio_sample")

    # Sample meta.
    sample_type = models.ForeignKey(BioSampleType,
                                    on_delete=models.CASCADE,
                                    related_name="bio_sample",
                                    verbose_name="Sample Type")
    sample_processing = models.CharField(default="None",
                                         blank=True,
                                         null=True,
                                         max_length=128,
                                         verbose_name="Sample Processing")
    freezing_temp = models.FloatField(blank=True, null=True, verbose_name="Freezing Temperature")
    thawing_time = models.IntegerField(blank=True, null=True, verbose_name="Thawing time")

    @classmethod
    def parse_fields_from_pandas_series(cls, series):
        """ Parse the pandas series for field values returning a dict. """
        sample_type = lower(get_field_value(series, cls, "sample_type"))
        sample_type = get_object_or_raise_validation(BioSampleType, name=sample_type)
        return dict(sample_type=sample_type,
                    sample_processing=get_field_value(series, cls, "sample_processing"),
                    freezing_temp=get_field_value(series, cls, "freezing_temp"),
                    thawing_time=get_field_value(series, cls, "thawing_time"))

    @property
    def center(self):
        return self.visit.patient.center

    def __str__(self):
        return f"{self.visit}_type:{self.sample_type}_pk{self.pk}"  # NOTE: str(self.visit) contains patient ID.


class SpectraMeasurementType(DatedModel):
    name = models.CharField(max_length=128, verbose_name="Spectra Measurement")

    def __str__(self):
        return self.name


class SpectralData(DatedModel):
    """ Model spectral data measured by spectrometer instrument. """

    class Meta:
        verbose_name = "Spectral Data"
        verbose_name_plural = verbose_name
        get_latest_by = "updated_at"

    UPLOAD_DIR = "spectral_data/"  # MEDIA_ROOT/spectral_data

    id = models.UUIDField(unique=True, primary_key=True, default=uuid.uuid4)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="spectral_data")
    bio_sample = models.ForeignKey(BioSample, on_delete=models.CASCADE, related_name="spectral_data")

    # Measurement info
    measurement_id = models.CharField(max_length=128, blank=True, null=True)
    measurement_type = models.ForeignKey(SpectraMeasurementType,
                                         on_delete=models.CASCADE,
                                         verbose_name="Measurement type",
                                         related_name="spectral_data")
    atr_crystal = models.CharField(max_length=128, blank=True, null=True, verbose_name="ATR Crystal")
    n_coadditions = models.IntegerField(blank=True, null=True, verbose_name="Number of coadditions")
    acquisition_time = models.IntegerField(blank=True, null=True, verbose_name="Acquisition time [s]")
    resolution = models.IntegerField(blank=True, null=True, verbose_name="Resolution [cm-1]")
    power = models.FloatField(max_length=128, blank=True, null=True, verbose_name="Power incident to the sample [mW]")
    temperature = models.FloatField(max_length=128, blank=True, null=True, verbose_name="Temperature [C]")
    pressure = models.FloatField(max_length=128, blank=True, null=True, verbose_name="Pressure [bar]")
    humidity = models.FloatField(max_length=128, blank=True, null=True, verbose_name="Humidity [%]")
    date = models.DateTimeField(blank=True, null=True)

    # SERS info.
    sers_description = models.CharField(max_length=128, blank=True, null=True, verbose_name="SERS description")
    sers_particle_material = models.CharField(max_length=128,
                                              blank=True,
                                              null=True,
                                              verbose_name="SERS particle material")
    sers_particle_size = models.FloatField(blank=True, null=True, verbose_name="SERS particle size [\u03BCm]")
    sers_particle_concentration = models.FloatField(blank=True, null=True, verbose_name="SERS particle concentration")

    data = models.FileField(upload_to=UPLOAD_DIR,
                            validators=[FileExtensionValidator(UploadedFile.FileFormats.choices())],
                            max_length=256,
                            verbose_name="Spectral data file")

    @classmethod
    def parse_fields_from_pandas_series(cls, series):
        """ Parse the pandas series for field values returning a dict. """
        measurement_type = lower(get_field_value(series, cls, "measurement_type"))
        measurement_type = get_object_or_raise_validation(SpectraMeasurementType, name=measurement_type)
        return dict(measurement_type=measurement_type,
                    acquisition_time=get_field_value(series, cls, "acquisition_time"),
                    n_coadditions=get_field_value(series, cls, "n_coadditions"),
                    resolution=get_field_value(series, cls, "resolution"),
                    atr_crystal=get_field_value(series, cls, "atr_crystal"),
                    power=get_field_value(series, cls, "power"),
                    temperature=get_field_value(series, cls, "temperature"),
                    pressure=get_field_value(series, cls, "pressure"),
                    humidity=get_field_value(series, cls, "humidity"),
                    date=get_field_value(series, cls, "date"),
                    sers_description=get_field_value(series, cls, "sers_description"),
                    sers_particle_material=get_field_value(series, cls, "sers_particle_material"),
                    sers_particle_size=get_field_value(series, cls, "sers_particle_size"),
                    sers_particle_concentration=get_field_value(series, cls, "sers_particle_concentration"))

    @property
    def center(self):
        return self.bio_sample.visit.patient.center

    def __str__(self):
        return str(self.generate_filename())

    def get_annotators(self):
        return list(set([annotation.annotator for annotation in self.qc_annotation.all()]))

    def get_unrun_annotators(self, existing_annotators=None):
        # Get annotators from existing annotations.
        if existing_annotators is None:
            existing_annotators = self.get_annotators()

        # Some default annotators may not have been run yet (newly added), so check.
        all_default_annotators = QCAnnotator.objects.filter(default=True)

        return list(set(all_default_annotators) - set(existing_annotators))

    def get_spectral_data(self):
        """ Return spectral data as instance of uploader.io.SpectralData. """
        return uploader.io.spectral_data_from_json(self.data)

    def generate_filename(self):
        return Path(f"{self.bio_sample.visit.patient.patient_id}_{self.bio_sample.pk}_{self.id}")\
            .with_suffix(uploader.io.FileFormats.JSONL)

    def clean_data_file(self):
        """ Read in data from uploaded file and store as json.

            The schema is equivalent to `json.dumps(dataclasses.asdict(uploader.io.SpectralData))``.
        """

        # Note: self.data is a FieldFile and is never None so check is "empty" instead, i.e., self.data.name is None.
        if not self.data:
            return

        try:
            data = uploader.io.read_spectral_data(self.data)
        except uploader.io.DataSchemaError as error:
            raise ValidationError(_("%(msg)s"), params={"msg": error})

        # Filenames need to be cleaned, however, don't clean TEMP filenames otherwise they won't be deleted.
        if Path(self.data.name).name.startswith(uploader.io.TEMP_FILENAME_PREFIX):
            filename = self.data.name
        else:
            filename = self.generate_filename()
        json_str = uploader.io.spectral_data_to_json(file=None, data=data)

        return ContentFile(json_str, name=filename)

    def clean(self):
        # Normalize data file format and clobber the uploaded file with the cleaned one.
        if (cleaned_file := self.clean_data_file()) is not None:
            # Update file.
            self.data = cleaned_file

    #@transaction.atomic(using="bsr")  # Really? Not sure if this even can be if run in background...
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

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

        # Compute QC metrics.
        # TODO: Even with the QC model being its own thing rather than fields here, we may still want to run here
        # such that new data is complete such that it has associated QC metrics.
        if settings.AUTO_ANNOTATE:
            # TODO: This should return early and runs async in the background.
            # See https://github.com/ssec-jhu/biospecdb/issues/77
            self.annotate()

    def asave(self, *args, **kwargs):
        raise NotImplementedError

    def delete(self, *args, **kwargs):
        count, deleted = super().delete(*args, **kwargs)
        if count == 1:
            os.remove(self.data.name)
        return count, deleted

    def adelete(self, *args, **kwargs):
        raise NotImplementedError


class ObservationsView(SqlView, models.Model):
    db = "bsr"

    class Meta:
        managed = False
        db_table = "v_observations"

    visit_id = models.BigIntegerField(primary_key=True)
    observation_id = models.ForeignKey(Observation, db_column="observation_id", on_delete=models.DO_NOTHING)
    observable_id = models.ForeignKey(Observable, db_column="observable_id", on_delete=models.DO_NOTHING)
    observable = deepcopy(Observable.name.field)
    observable.name = observable.db_column = "observable"
    value_class = deepcopy(Observable.value_class.field)
    days_observed = deepcopy(Observation.days_observed.field)
    observable_value = deepcopy(Observation.observable_value.field)

    @classmethod
    def sql(cls):
        sql = f"""
        CREATE VIEW {cls._meta.db_table} AS
        SELECT s.visit_id,
               s.id AS observation_id,
               d.id AS observable_id,
               d.name AS observable,
               d.value_class,
               s.days_observed,
               s.observable_value
        FROM uploader_observation s
        JOIN uploader_observable d ON d.id=s.observable_id
        """  # nosec B608
        return sql, None


class VisitObservationsView(SqlView, models.Model):
    class Meta:
        managed = False
        db_table = "v_visit_observations"

    sql_view_dependencies = (ObservationsView,)
    db = "bsr"

    visit_id = models.BigIntegerField(primary_key=True)

    @classmethod
    def sql(cls):
        observables = Observable.objects.all()
        view = cls._meta.db_table
        d = []
        for observable in observables:
            secure_name(observable.name)
            if observable.value_class == "FLOAT":
                value = 'cast(observable_value AS REAL)'
            elif observable.value_class == "INTEGER":
                value = "cast(observable_value AS INTEGER)"
            else:
                value = "observable_value"
            d.append(f"max(case when observable = '{observable.name}' then {value} else null end) as "
                     f"[{observable.name}]")

        d = "\n,      ".join(d)

        # NOTE: Params aren't allowed in view statements with sqlite. Since observable can be added to the DB this poses
        # as a risk since someone with access to creating observables could inject into observable.name arbitrary SQL.
        # Calling secure_name(observable.name) may not entirely guard against this even though its intention is to do
        # so.
        sql = f"""
        create view {view} as
        select visit_id
        ,      {d} 
          from v_observations 
         group by visit_id
        """  # nosec B608

        return sql, None


class FullPatientView(SqlView, models.Model):
    class Meta:
        managed = False
        db_table = "full_patient"

    sql_view_dependencies = (VisitObservationsView,)
    db = "bsr"

    @classmethod
    def sql(cls):
        sql = f"""
                create view {cls._meta.db_table} as 
                select p.patient_id, p.gender
                ,      bst.name, bs.sample_processing, bs.freezing_temp, bs.thawing_time
                ,      i.manufacturer, i.model
                ,      sdt.name, sd.acquisition_time, sd.n_coadditions, sd.resolution, sd.data
                ,      vs.*
                  from uploader_patient p
                  join uploader_visit v on p.patient_id=v.patient_id
                  join uploader_biosample bs on bs.visit_id=v.id
                  join uploader_biosampletype bst on bst.id=bs.sample_type_id
                  join uploader_spectraldata sd on sd.bio_sample_id=bs.id
                  join uploader_spectrameasurementtype sdt on sdt.id=sd.measurement_type_id
                  join uploader_instrument i on i.id=sd.instrument_id
                  left outer join v_visit_observations vs on vs.visit_id=v.id
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


class QCAnnotator(DatedModel):
    class Meta:
        get_latest_by = "updated_at"

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


class QCAnnotation(DatedModel):

    class Meta:
        unique_together = [["annotator", "spectral_data"]]
        get_latest_by = "updated_at"

    value = models.CharField(blank=True, null=True, max_length=128)

    annotator = models.ForeignKey(QCAnnotator,
                                  blank=False,
                                  null=False,
                                  on_delete=models.CASCADE,
                                  related_name="qc_annotation")
    spectral_data = models.ForeignKey(SpectralData, on_delete=models.CASCADE, related_name="qc_annotation")

    @property
    def center(self):
        return self.spectral_data.bio_samaple.visit.patient.center

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

    def save(self, *args, **kwargs):
        self.run(save=False)
        super().save(*args, **kwargs)

    def asave(self, *args, **kwargs):
        raise NotImplementedError


def get_center(obj):
    if isinstance(obj, Center):
        return obj
    elif isinstance(obj, UserBaseCenter):
        try:
            return Center.objects.get(pk=obj.pk)
        except Center.DoesNotExist:
            return
    elif hasattr(obj, "center"):
        return obj.center


# This is Model B wo/ observable table https://miro.com/app/board/uXjVMAAlj9Y=/
# class Observations(models.Model):
#     visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="observations")
#
#     # SARS-CoV-2 (COVID) viral load indicators.
#     Ct_gene_N = models.FloatField()
#     Ct_gene_ORF1ab = models.FloatField()
#     Covid_RT_qPCR = models.CharField(default=NEGATIVE, choices=(NEGATIVE, POSITIVE))
#     suspicious_contact = models.BooleanField(default=False)
#
#     # Observations/Observables
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
