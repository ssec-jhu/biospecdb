import os
from pathlib import Path

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

from uploader.io import read_meta_data, read_spectral_data_table, spectral_data_to_csv


class ExitTransaction(Exception):
    ...


TEMP_FILENAME_PREFIX = "__TEMP__"


def save_data_to_db(meta_data, spectral_data, center=None, joined_data=None, dry_run=False) -> dict:

    """
    Ingest into the database large tables of symptom & disease data (aka "meta" data) along with associated spectral
    data.

    Note: Data can be passed in pre-joined, i.e., save_data_to_db(None, None, joined_data). If so, data can't be
          validated.
    Note: This func is called by UploadedFile.clean() which, therefore, can't also be called here.
    """
    from uploader.models import BioSample, Disease, Instrument, Patient, SpectralData, Symptom, UploadedFile, Visit,\
        Center as UploaderCenter
    from user.models import Center as UserCenter

    # Only user.models.User can relate to user.models,Center, all uploader models must use uploader.models.Center since
    # these two apps live on separate databases.
    if center and isinstance(center, UserCenter):
        center = UploaderCenter.objects.get(pk=center.pk)

    if joined_data is None:
        # Read in all data.
        meta_data = meta_data if isinstance(meta_data, pd.DataFrame) else read_meta_data(meta_data)
        spec_data = spectral_data if isinstance(spectral_data, pd.DataFrame) else \
            read_spectral_data_table(spectral_data)

        UploadedFile.validate_lengths(meta_data, spec_data)
        joined_data = UploadedFile.join_with_validation(meta_data, spec_data)

    try:
        with transaction.atomic(using="bsr"):
            spectral_data_files = []

            # Ingest into db.
            for index, row in joined_data.iterrows():
                # NOTE: The pattern for column lookup is to use get(..., default=None) and defer the field validation,
                # i.e., whether null/blank etc., to the actual field def.

                # Patient
                try:
                    # NOTE: ValidationError is raised when ``index`` is not a UUID, or not UUID-like, e.g., 1 is ok (as
                    # it's an int), however, '1' isn't. Here ``index`` is a string - and needs to be for UUIDs.
                    patient = Patient.objects.get(pk=index)
                except (Patient.DoesNotExist, ValidationError):
                    try:
                        # Allow patients to be referenced by both patient_id and patient_cid.
                        patient = Patient.objects.get(patient_cid=index)
                    except (Patient.DoesNotExist, ValidationError):
                        # NOTE: We do not use the ``index`` read from file as the pk even if it is a UUID. The above
                        # ``get()`` only allows for existing patients to be re-used when _already_ in the db with their
                        # pk already auto-generated.
                        patient = Patient(gender=Patient.Gender(row.get(Patient.gender.field.verbose_name.lower())),
                                          patient_id=index,
                                          center=center)
                        patient.full_clean()
                        patient.save()

                # Visit
                # TODO: Add logic to auto-find previous_visit. https://github.com/ssec-jhu/biospecdb/issues/37
                visit = Visit(patient=patient,
                              patient_age=row.get(Visit.patient_age.field.verbose_name.lower()),
                              )
                visit.full_clean()
                visit.save()

                # BioSample
                biosample = BioSample(visit=visit,
                                      sample_type=BioSample.SampleKind(
                                          row.get(BioSample.sample_type.field.verbose_name.lower())),
                                      sample_processing=row.get(BioSample.sample_processing.field.verbose_name.lower()),
                                      freezing_temp=row.get(BioSample.freezing_temp.field.verbose_name.lower()),
                                      thawing_time=row.get(BioSample.thawing_time.field.verbose_name.lower()))
                visit.bio_sample.add(biosample, bulk=False)
                biosample.full_clean()
                biosample.save()

                # SpectralData
                spectrometer = row.get(Instrument.spectrometer.field.verbose_name.lower())
                atr_crystal = row.get(Instrument.atr_crystal.field.verbose_name.lower())
                # NOTE: get_or_create() returns a tuple of (object, created), where created is a bool.
                instrument, created = Instrument.objects.get_or_create(spectrometer__iexact=spectrometer,
                                                                       atr_crystal__iexact=atr_crystal)
                if created:
                    raise ValidationError(f"New Instruments can only be added by admin: instrument details:"
                                          f"spectrometer: '{spectrometer}' and atr_crystal: '{atr_crystal}'")
                # NOTE: get_or_create() doesn't clean, so we clean after the fact. This is ok since this entire func is
                # transactional.
                # TODO: Remove this redundant clean upon resolving https://github.com/ssec-jhu/biospecdb/issues/28.
                instrument.full_clean()

                # Create datafile
                wavelengths = row["wavelength"]
                intensities = row["intensity"]

                csv_data = spectral_data_to_csv(file=None, wavelengths=wavelengths, intensities=intensities)

                # Note: This won't be unique since multiple files can exist per biosample. However, we'd have to create
                # this post save such as to mangle in spectraldata.pk. Instead, django will automatically append a
                # random 7 digit string before the ext upon file name collisions.
                data_filename = Path(f"{TEMP_FILENAME_PREFIX if dry_run else ''}{patient.patient_id}_{biosample.pk}").\
                    with_suffix(str(UploadedFile.FileFormats.CSV))

                spectraldata = SpectralData(instrument=instrument,
                                            bio_sample=biosample,
                                            spectra_measurement=SpectralData.SpectralMeasurementKind(
                                                row.get(SpectralData.spectra_measurement.field.verbose_name.lower())
                                            ),
                                            acquisition_time=row.get(
                                                SpectralData.acquisition_time.field.verbose_name.lower()),
                                            n_coadditions=row.get(
                                                SpectralData.n_coadditions.field.verbose_name.lower()),
                                            resolution=row.get(SpectralData.resolution.field.verbose_name.lower()),

                                            # TODO: See https://github.com/ssec-jhu/biospecdb/issues/40
                                            data=ContentFile(csv_data, name=data_filename))
                biosample.spectral_data.add(spectraldata, bulk=False)

                instrument.spectral_data.add(spectraldata, bulk=False)
                spectraldata.full_clean()
                spectraldata.save()
                spectral_data_files.append(Path(spectraldata.data.name))

                # Symptoms
                # NOTE: Bulk data from client doesn't contain data for `days_symptomatic` per symptom, but instead per
                # patient.
                days_symptomatic = row.get(Symptom.days_symptomatic.field.verbose_name.lower(), None)
                for disease in Disease.objects.all():
                    symptom_value = row.get(disease.alias.lower(), None)
                    if symptom_value is None:
                        continue

                    # TODO: Should the following logic belong to Symptom.__init__()?
                    #  See https://github.com/ssec-jhu/biospecdb/issues/42
                    symptom_value = Disease.Types(disease.value_class).cast(symptom_value)
                    symptom = Symptom(disease=disease,
                                      visit=visit,
                                      disease_value=symptom_value,
                                      days_symptomatic=days_symptomatic)

                    disease.symptom.add(symptom, bulk=False)
                    symptom.full_clean()
                    symptom.save()

            if dry_run:
                raise ExitTransaction()
    except ExitTransaction:
        pass
    except Exception:
        # Something went wrong and the above transaction was aborted so delete uncommitted and now orphaned files.
        while spectral_data_files:
            os.remove(spectral_data_files.pop())  # Pop to avoid repetition in finally branch.
        raise
    finally:
        # Delete unwanted temporary files.
        for file in spectral_data_files:
            if file.name.startswith(TEMP_FILENAME_PREFIX):
                os.remove(file)


def update_db(meta_data, spectral_data, joined_data=None, dry_run=False) -> dict:
    """
    Ingest into the database large tables of symptom & disease data (aka "meta" data) along with associated spectral
    data.

    Note: Data can be passed in pre-joined, i.e., save_data_to_db(None, None, joined_data). If so, data can't be
          validated.
    Note: This func is called by UploadedFile.clean() which, therefore, can't also be called here.
    """
    from uploader.models import BioSample, Disease, Instrument, Patient, SpectralData, Symptom, UploadedFile, Visit

    if joined_data is None:
        # Read in all data.
        meta_data = meta_data if isinstance(meta_data, pd.DataFrame) else read_meta_data(meta_data)
        spec_data = spectral_data if isinstance(spectral_data, pd.DataFrame) else \
            read_spectral_data_table(spectral_data)

        UploadedFile.validate_lengths(meta_data, spec_data)
        joined_data = UploadedFile.join_with_validation(meta_data, spec_data)

    try:
        with transaction.atomic(using="bsr"):
            # Ingest into db.
            for index, row in joined_data.iterrows():
                # NOTE: The pattern for column lookup is to use get(..., default=None) and defer the field validation,
                # i.e., whether null/blank etc., to the actual field def.

                # Patient
                try:
                    # NOTE: ValidationError is raised when ``index`` is not a UUID, or not UUID-like, e.g., 1 is ok (as
                    # it's an int), however, '1' isn't. Here ``index`` is a string - and needs to be for UUIDs.
                    patient = Patient.objects.get(pk=index)
                except (Patient.DoesNotExist, ValidationError):
                    # NOTE: We do not use the ``index`` read from file as the pk even if it is a UUID. The above
                    # ``get()`` only allows for existing patients to be re-used when _already_ in the db with their pk
                    # already auto-generated.
                    patient = Patient(gender=Patient.Gender(row.get(Patient.gender.field.verbose_name.lower())),
                                      patient_id=index)
                    patient.full_clean()
                    patient.save()

                # Visit
                # TODO: Add logic to auto-find previous_visit. https://github.com/ssec-jhu/biospecdb/issues/37
                visit = Visit(patient=patient,
                              patient_age=row.get(Visit.patient_age.field.verbose_name.lower()),
                              )
                visit.full_clean()
                visit.save()

                # BioSample
                biosample = BioSample(visit=visit,
                                      sample_type=BioSample.SampleKind(
                                          row.get(BioSample.sample_type.field.verbose_name.lower())),
                                      sample_processing=row.get(BioSample.sample_processing.field.verbose_name.lower()),
                                      freezing_temp=row.get(BioSample.freezing_temp.field.verbose_name.lower()),
                                      thawing_time=row.get(BioSample.thawing_time.field.verbose_name.lower()))
                visit.bio_sample.add(biosample, bulk=False)
                biosample.full_clean()
                biosample.save()

                # SpectralData
                spectrometer = row.get(Instrument.spectrometer.field.verbose_name.lower())
                atr_crystal = row.get(Instrument.atr_crystal.field.verbose_name.lower())
                # NOTE: get_or_create() returns a tuple of (object, created), where created is a bool.
                instrument, created = Instrument.objects.get_or_create(spectrometer__iexact=spectrometer,
                                                                       atr_crystal__iexact=atr_crystal)
                if created:
                    raise ValidationError(f"New Instruments can only be added by admin: instrument details:"
                                          f"spectrometer: '{spectrometer}' and atr_crystal: '{atr_crystal}'")
                # NOTE: get_or_create() doesn't clean, so we clean after the fact. This is ok since this entire func is
                # transactional.
                # TODO: Remove this redundant clean upon resolving https://github.com/ssec-jhu/biospecdb/issues/28.
                instrument.full_clean()

                # Create datafile
                wavelengths = row["wavelength"]
                intensities = row["intensity"]

                csv_data = spectral_data_to_csv(file=None, wavelengths=wavelengths, intensities=intensities)
                data_filename = Path(str(Visit)).with_suffix(str(UploadedFile.FileFormats.CSV))

                spectraldata = SpectralData(instrument=instrument,
                                            bio_sample=biosample,
                                            spectra_measurement=SpectralData.SpectralMeasurementKind(
                                                row.get(SpectralData.spectra_measurement.field.verbose_name.lower())
                                            ),
                                            acquisition_time=row.get(
                                                SpectralData.acquisition_time.field.verbose_name.lower()),
                                            n_coadditions=row.get(
                                                SpectralData.n_coadditions.field.verbose_name.lower()),
                                            resolution=row.get(SpectralData.resolution.field.verbose_name.lower()),

                                            # TODO: See https://github.com/ssec-jhu/biospecdb/issues/40
                                            data=ContentFile(csv_data, name=data_filename))
                biosample.spectral_data.add(spectraldata, bulk=False)

                instrument.spectral_data.add(spectraldata, bulk=False)
                spectraldata.full_clean()
                spectraldata.save()

                # Symptoms
                # NOTE: Bulk data from client doesn't contain data for `days_symptomatic` per symptom, but instead per
                # patient.
                days_symptomatic = row.get(Symptom.days_symptomatic.field.verbose_name.lower(), None)
                for disease in Disease.objects.all():
                    symptom_value = row.get(disease.alias.lower(), None)
                    if symptom_value is None:
                        continue

                    # TODO: Should the following logic belong to Symptom.__init__()?
                    #  See https://github.com/ssec-jhu/biospecdb/issues/42
                    symptom_value = Disease.Types(disease.value_class).cast(symptom_value)
                    symptom = Symptom(disease=disease,
                                      visit=visit,
                                      disease_value=symptom_value,
                                      days_symptomatic=days_symptomatic)

                    disease.symptom.add(symptom, bulk=False)
                    symptom.full_clean()
                    symptom.save()

            if dry_run:
                raise ExitTransaction()
    except ExitTransaction:
        pass
