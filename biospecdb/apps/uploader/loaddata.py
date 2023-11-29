from pathlib import Path

import pandas as pd
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction

import uploader.io


class ExitTransaction(Exception):
    ...


def save_data_to_db(meta_data, spectral_data, center=None, joined_data=None, dry_run=False) -> dict:

    """
    Ingest into the database large tables of observation & observable data (aka "meta" data) along with associated
    spectral data.

    Note: Data can be passed in pre-joined, i.e., save_data_to_db(None, None, joined_data). If so, data can't be
          validated.
    Note: This func is called by UploadedFile.clean() which, therefore, can't also be called here.
    """
    from uploader.models import BioSample, Observable, Instrument, Patient, SpectralData, Observation, UploadedFile,\
        Visit, Center as UploaderCenter, BioSampleType, SpectraMeasurementType
    from user.models import Center as UserCenter

    # Only user.models.User can relate to user.models,Center, all uploader models must use uploader.models.Center since
    # these two apps live on separate databases.
    if center and isinstance(center, UserCenter):
        center = UploaderCenter.objects.get(pk=center.pk)

    if joined_data is None:
        # Read in all data.
        meta_data = meta_data if isinstance(meta_data, pd.DataFrame) else uploader.io.read_meta_data(meta_data)
        spec_data = spectral_data if isinstance(spectral_data, pd.DataFrame) else \
            uploader.io.read_spectral_data_table(spectral_data)

        UploadedFile.validate_lengths(meta_data, spec_data)
        joined_data = UploadedFile.join_with_validation(meta_data, spec_data)

    has_patient_cid = Patient.patient_cid.field.verbose_name.lower() in joined_data.columns
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
                    if has_patient_cid:
                        try:
                            # Allow patients to be referenced by both patient_id and patient_cid.
                            # Note: patient_cid is only guaranteed to be unique to a center and not by itself.
                            patient_cid = row.get(Patient.patient_cid.field.verbose_name.lower())
                            patient = Patient.objects.get(patient_cid=patient_cid, center=center)

                    else:
                        # NOTE: We do not use the ``index`` read from file as the pk even if it is a UUID. The above
                        # ``get()`` only allows for existing patients to be re-used when _already_ in the db with their
                        # pk already auto-generated.
                        patient = Patient(gender=Patient.Gender(row.get(Patient.gender.field.verbose_name.lower())),
                                          patient_id=index,
                                          center=center)
                        patient.full_clean()
                        patient.save()

                    try:
                        # Allow patients to be referenced by both patient_id and patient_cid.
                        # Note: patient_cid is only guaranteed to be unique to a center and not by itself.
                        patient_cid = row.get(Patient.patient_cid.field.verbose_name.lower())

                        patient = Patient.objects.get(patient_cid=patient_cid, center=center)
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
                                      sample_type=BioSampleType.objects.get(name=row.get(
                                          BioSample.sample_type.field.verbose_name.lower()).lower()),
                                      sample_processing=row.get(BioSample.sample_processing.field.verbose_name.lower()),
                                      freezing_temp=row.get(BioSample.freezing_temp.field.verbose_name.lower()),
                                      thawing_time=row.get(BioSample.thawing_time.field.verbose_name.lower()))
                biosample.full_clean()
                biosample.save()
                visit.bio_sample.add(biosample, bulk=False)

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
                json_str = uploader.io.spectral_data_to_json(file=None,
                                                             data=None,
                                                             patient_id=index,
                                                             wavelength=row["wavelength"],
                                                             intensity=row["intensity"])

                spectral_measurement_kind = SpectraMeasurementType.objects.get(name=row.get(
                    SpectralData.spectra_measurement.field.verbose_name.lower()).lower())

                spectraldata = SpectralData(instrument=instrument,
                                            bio_sample=biosample,
                                            spectra_measurement=spectral_measurement_kind,
                                            acquisition_time=row.get(
                                                SpectralData.acquisition_time.field.verbose_name.lower()),
                                            n_coadditions=row.get(
                                                SpectralData.n_coadditions.field.verbose_name.lower()),
                                            resolution=row.get(SpectralData.resolution.field.verbose_name.lower()))
                filename = f"{uploader.io.TEMP_FILENAME_PREFIX if dry_run else ''}{spectraldata.generate_filename()}"
                spectraldata.data = ContentFile(json_str, name=filename)
                spectraldata.full_clean()
                spectraldata.save()
                spectral_data_files.append(spectraldata.data)

                biosample.spectral_data.add(spectraldata, bulk=False)
                instrument.spectral_data.add(spectraldata, bulk=False)

                # Observations
                # NOTE: Bulk data from client doesn't contain data for `days_observed` per observation, but instead per
                # patient.
                days_observed = row.get(Observation.days_observed.field.verbose_name.lower(), None)
                for observable in Observable.objects.all():
                    observation_value = row.get(observable.alias.lower(), None)
                    if observation_value is None:
                        continue

                    # TODO: Should the following logic belong to Observation.__init__()?
                    #  See https://github.com/ssec-jhu/biospecdb/issues/42
                    observation_value = Observable.Types(observable.value_class).cast(observation_value)
                    observation = Observation(observable=observable,
                                      visit=visit,
                                      observable_value=observation_value,
                                      days_observed=days_observed)

                    observation.full_clean()
                    observation.save()
                    observable.observation.add(observation, bulk=False)

            if dry_run:
                raise ExitTransaction()
    except ExitTransaction:
        pass
    except Exception:
        # Something went wrong and the above transaction was aborted so delete uncommitted and now orphaned files.
        while spectral_data_files:
            file = spectral_data_files.pop()
            if not file.closed:
                file.close()
            SpectralData.data.field.storage.delete(file.name)  # Pop to avoid repetition in finally branch.
        raise
    finally:
        # Delete unwanted temporary files.
        for file in spectral_data_files:
            if (filename := Path(file.name)).name.startswith(uploader.io.TEMP_FILENAME_PREFIX):
                if not file.closed:
                    file.close()
                SpectralData.data.field.storage.delete(filename)
