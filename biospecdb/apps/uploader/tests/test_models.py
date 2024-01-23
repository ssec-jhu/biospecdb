from pathlib import Path
from uuid import uuid4

from django.core.exceptions import ValidationError
import django.core.files
from django.core.files.base import ContentFile
from django.db.utils import IntegrityError
import pytest

import uploader.io
from uploader.models import BioSample, BioSampleType, Observable, Instrument, Patient, SpectralData, Observation,\
    Visit, UploadedFile, get_center, Center, SpectraMeasurementType
from uploader.loaddata import save_data_to_db
from user.models import Center as UserCenter
from uploader.models import Center as UploaderCenter
import biospecdb.util
from uploader.tests.conftest import bulk_upload, DATA_PATH


@pytest.mark.django_db(databases=["default", "bsr"])
class TestPatient:
    def test_creation(self, center):
        Patient(gender=Patient.Gender.MALE, center=center).full_clean()
        Patient(gender=Patient.Gender.FEMALE, center=center).full_clean()
        Patient(gender=Patient.Gender.UNSPECIFIED, center=center).full_clean()

    def test_db_creation(self, center):
        Patient.objects.create(gender=Patient.Gender.MALE, center=center).full_clean()
        Patient.objects.create(gender=Patient.Gender.FEMALE, center=center).full_clean()
        Patient.objects.create(gender=Patient.Gender.UNSPECIFIED, center=center).full_clean()

        assert len(Patient.objects.all()) == 3

        Patient.objects.create(gender=Patient.Gender.MALE, center=center).full_clean()
        assert len(Patient.objects.all()) == 4

        males = Patient.objects.filter(gender=Patient.Gender.MALE, center=center)
        females = Patient.objects.filter(gender=Patient.Gender.FEMALE, center=center)
        unspecified = Patient.objects.filter(gender=Patient.Gender.UNSPECIFIED, center=center)
        
        assert len(males) == 2
        assert len(females) == 1
        assert len(unspecified) == 1
        
        assert males[0].patient_id != males[1].patient_id

    def test_short_name(self, center):
        patient = Patient(gender=Patient.Gender.MALE, center=center)
        patient.full_clean()
        assert patient.short_id() in str(patient)

    def test_gender_validation(self, center):
        Patient(gender=Patient.Gender.MALE, center=center).full_clean()

        with pytest.raises(ValidationError):
            Patient(gender="blah").full_clean()

    def test_fixture_data(self, db, patients):
        assert len(Patient.objects.all()) == 3
        assert Patient.objects.get(pk="437de0d7-6618-4445-bab2-03822310b0ef")

    def test_editable_patient_id(self, center):
        patient_id = uuid4()
        Patient.objects.create(patient_id=patient_id, gender=Patient.Gender.FEMALE, center=center)
        assert Patient.objects.get(pk=patient_id)

    def test_center_validation(self, centers):
        center = UploaderCenter.objects.get(name="SSEC")
        assert UserCenter.objects.filter(pk=center.pk).exists()
        assert UploaderCenter.objects.filter(pk=center.pk).exists()

        # OK.
        patient_id = uuid4()
        patient = Patient(patient_id=patient_id, gender=Patient.Gender.FEMALE, center=center)
        patient.full_clean()

        # Not OK.
        patient_id = uuid4()
        with pytest.raises(ValueError, match="Cannot assign"):
            patient = Patient(patient_id=patient_id,
                              gender=Patient.Gender.FEMALE,
                              center=UserCenter.objects.get(name="SSEC"))

    def test_unique_cid_center_id(self, centers):
        center = UploaderCenter.objects.get(name="SSEC")
        cid = uuid4()
        Patient.objects.create(patient_id=uuid4(),
                               gender=Patient.Gender.FEMALE,
                               center=center,
                               patient_cid=cid)
        # OK.
        Patient.objects.create(patient_id=uuid4(),
                               gender=Patient.Gender.FEMALE,
                               center=center,
                               patient_cid=uuid4())

        # OK.
        Patient.objects.create(patient_id=uuid4(),
                               gender=Patient.Gender.FEMALE,
                               center=UploaderCenter.objects.get(name="Imperial College London"),
                               patient_cid=cid)

        # Not OK.
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed:"):
            Patient.objects.create(patient_id=uuid4(),
                                   gender=Patient.Gender.FEMALE,
                                   center=center,
                                   patient_cid=cid)

    def test_pi_cid_validation(self, centers):
        id = uuid4()
        patient = Patient(patient_id=id,
                          gender=Patient.Gender.UNSPECIFIED,
                          patient_cid=id,
                          center=Center.objects.get(name="SSEC"))
        with pytest.raises(ValidationError, match="Patient ID and patient CID cannot be the same"):
            patient.full_clean()


@pytest.mark.django_db(databases=["default", "bsr"])
class TestVisit:
    ...


@pytest.mark.django_db(databases=["default", "bsr"])
class TestObservable:
    def test_fixture_data(self, db, observables):
        observable = Observable.objects.get(pk=1)
        assert observable.name == "Ct_gene_N"
        assert observable.value_class == Observable.Types.FLOAT

    def test_name_uniqueness(self, db):
        Observable.objects.create(name="A", description="blah", alias="a", category=Observable.Category.COMORBIDITY)
        with pytest.raises(IntegrityError, match="unique_observable_name"):
            Observable.objects.create(name="a", description="blah", alias="b", category=Observable.Category.COMORBIDITY)

    def test_alias_uniqueness(self, db):
        Observable.objects.create(name="A", description="blah", alias="a", category=Observable.Category.COMORBIDITY)
        with pytest.raises(IntegrityError, match="unique_alias_name"):
            Observable.objects.create(name="b", description="blah", alias="A", category=Observable.Category.COMORBIDITY)


@pytest.mark.django_db(databases=["default", "bsr"])
class TestInstrument:
    def test_fixture_data(self, db, instruments):
        Instrument.objects.get(pk="4205d8ac-90c1-4529-90b2-6751f665c403")

    def test_new(self, db, instruments):
        Instrument.objects.create()
        assert Instrument.objects.count() == 2


@pytest.mark.django_db(databases=["default", "bsr"])
class TestObservation:
    def test_observable_value_validation(self, db, observables, visits):
        observation = Observation.objects.create(visit=Visit.objects.get(pk=1),
                                                 observable=Observable.objects.get(name="Ct_gene_N"),
                                                 observable_value="strings can't cast to floats")
        with pytest.raises(ValidationError):
            observation.full_clean()

    @pytest.mark.parametrize("value", (True, False))
    def test_observable_value_bool_cast(self, db, observables, visits, value):
        observation = Observation.objects.create(visit=Visit.objects.get(pk=1),
                                                 observable=Observable.objects.get(name="fever"),
                                                 observable_value=str(value))
        observation.full_clean()
        assert observation.observable_value is value

    def test_center_validation(self, centers):
        center = Center.objects.get(name="SSEC")
        patient = Patient.objects.create(center=center)
        visit = Visit.objects.create(patient_age=40, patient=patient)

        # OK.
        observable = Observable.objects.create(name="snuffles",
                                               alias="snuffles",
                                               center=center,
                                               category=Observable.Category.SYMPTOM)
        Observation(visit=visit, observable=observable).full_clean()

        # OK.
        observable = Observable.objects.create(name="extra_snuffles",
                                               alias="extra snuffles",
                                               center=None,
                                               category=Observable.Category.SYMPTOM)
        Observation(visit=visit, observable=observable).full_clean()

        # Not OK.
        center
        observable = Observable.objects.create(name="even_more_snuffles",
                                               alias="even more snuffles",
                                               center=Center.objects.get(name="Imperial College London"),
                                               category=Observable.Category.SYMPTOM)
        with pytest.raises(ValidationError, match="Patient observation observable category must belong to patient "
                                                  "center:"):
            Observation(visit=visit, observable=observable).full_clean()


@pytest.mark.django_db(databases=["default", "bsr"])
class TestBioSample:
    ...


@pytest.mark.django_db(databases=["default", "bsr"])
class TestSpectralData:
    def test_files_added(self, mock_data_from_files):
        n_patients = 10
        assert len(SpectralData.objects.all()) == n_patients
        for obj in SpectralData.objects.all():
            assert Path(obj.data.name).exists()

    def test_no_file_validation(self, db):
        """ Test that a validation error is raised rather than any other python exception which would indicate a bug.
            See https://github.com/ssec-jhu/biospecdb/pull/181
        """
        data = SpectralData()
        with pytest.raises(ValidationError):
            data.full_clean()

    def test_temp_files_deleted(self, mock_data_from_files):
        n_patients = 10
        assert len(SpectralData.objects.all()) == n_patients
        filename = Path(SpectralData.objects.all()[0].data.name)
        assert filename.parent.exists()
        assert filename.parent.is_dir()
        assert not list(filename.parent.glob(f"{uploader.io.TEMP_FILENAME_PREFIX}*"))

    def test_no_duplicate_data_files(self, mock_data_from_files):
        n_patients = 10
        assert len(SpectralData.objects.all()) == n_patients
        filename = Path(SpectralData.objects.all()[0].data.name)
        assert filename.parent.exists()
        assert filename.parent.is_dir()
        assert len(list(filename.parent.glob('*'))) == n_patients

    @pytest.mark.skip("Unimplemented See #141")
    def test_all_files_deleted_upon_transaction_failure(self):
        # I'm not sure how to mock this... See https://github.com/ssec-jhu/biospecdb/issues/141
        ...

    @pytest.mark.parametrize("ext", uploader.io.FileFormats.list())
    def test_clean(self, centers, instruments, ext, bio_sample_types, spectra_measurement_types):
        data_file = (DATA_PATH/"sample").with_suffix(ext)
        data = uploader.io.read_spectral_data(data_file)

        patient = Patient.objects.create(patient_id=data.patient_id,
                                         center=Center.objects.get(name="SSEC"))
        visit = patient.visit.create(patient_age=40)
        bio_sample = visit.bio_sample.create(sample_type=BioSampleType.objects.get(name="pharyngeal swab"))

        spectral_data = SpectralData(instrument=Instrument.objects.get(pk="4205d8ac-90c1-4529-90b2-6751f665c403"),
                                     bio_sample=bio_sample,
                                     data=ContentFile(data_file.read_bytes(), name=data_file),
                                     measurement_type=SpectraMeasurementType.objects.get(name="atr-ftir"))
        spectral_data.full_clean()
        spectral_data.save()

        assert Path(spectral_data.data.name).suffix == uploader.io.FileFormats.JSONL
        cleaned_data = spectral_data.get_spectral_data()
        assert cleaned_data == data


@pytest.mark.django_db(databases=["default", "bsr"])
class TestUploadedFile:
    @pytest.mark.parametrize("file_ext", UploadedFile.FileFormats.list())
    def test_upload_without_error(self,
                                  db,
                                  observables,
                                  instruments,
                                  file_ext,
                                  center,
                                  bio_sample_types,
                                  spectra_measurement_types):
        meta_data_path = (DATA_PATH/"meta_data").with_suffix(file_ext)
        spectral_file_path = (DATA_PATH / "spectral_data").with_suffix(file_ext)
        with meta_data_path.open(mode="rb") as meta_data, spectral_file_path.open(mode="rb") as spectral_data:
            data_upload = UploadedFile(meta_data_file=django.core.files.File(meta_data,
                                                                             name=meta_data_path.name),
                                       spectral_data_file=django.core.files.File(spectral_data,
                                                                                 name=spectral_file_path.name),
                                       center=center)
            data_upload.clean()
            data_upload.save()

    def test_mock_data_from_files_fixture(self, mock_data_from_files):
        n_patients = 10
        assert len(UploadedFile.objects.all()) == 1
        assert len(Patient.objects.all()) == n_patients
        assert len(Visit.objects.all()) == n_patients
        assert len(BioSample.objects.all()) == n_patients
        assert len(SpectralData.objects.all()) == n_patients

    def test_center(self, mock_data_from_files):
        n_patients = len(Patient.objects.all())
        assert n_patients == 10
        center = Center.objects.get(name="SSEC")
        assert n_patients == len(Patient.objects.filter(center=center))
        assert not Patient.objects.filter(center=None)

    def test_mock_data_fixture(self, mock_data):
        n_patients = 10
        assert len(Patient.objects.all()) == n_patients
        assert len(Visit.objects.all()) == n_patients
        assert len(BioSample.objects.all()) == n_patients
        assert len(SpectralData.objects.all()) == n_patients

    def test_number_observations(self,
                                 db,
                                 observables,
                                 instruments,
                                 center,
                                 bio_sample_types,
                                 spectra_measurement_types):
        """ The total number of observations := N_patients * N_observables. """
        assert len(Patient.objects.all()) == 0  # Assert empty.

        save_data_to_db(DATA_PATH / "meta_data.csv",
                        DATA_PATH / "spectral_data.csv",
                        center=center)

        n_patients = len(Patient.objects.all())
        n_observables = len(Observable.objects.all())
        n_observations = len(Observation.objects.all())

        # Assert not empty.
        assert n_patients > 0
        assert n_observables > 0
        assert n_observations > 0

        # When Covid_RT_qPCR is negative both Ct_gene_N & Ct_gene_ORF1ab observations will be null and omitted.
        # This must be accounted for in the total.
        n_empty_covid_observations = len((Observation.objects.filter(observable=Observable.objects.
                                                                     get(name="Covid_RT_qPCR")))
                                         .filter(observable_value="Negative"))
        assert n_observations == n_patients * n_observables - n_empty_covid_observations * 2

    @pytest.mark.parametrize("file_ext", UploadedFile.FileFormats.list())
    def test_patient_ids(self, mock_data_from_files, file_ext):
        meta_data_path = (DATA_PATH / "meta_data").with_suffix(file_ext)
        df = uploader.io.read_meta_data(meta_data_path)

        all_patients = Patient.objects.all()

        assert len(all_patients) == len(df)
        for index in df.index:
            assert all_patients.get(pk=index)

    @pytest.mark.parametrize("file_ext", UploadedFile.FileFormats.list())
    def test_index_match_validation(self, db, observables, instruments, file_ext, tmp_path):
        meta_data_path = (DATA_PATH / "meta_data").with_suffix(file_ext)

        biospecdb.util.mock_bulk_spectral_data(path=tmp_path)
        spectral_file_path = tmp_path / "spectral_data.csv"
        with meta_data_path.open(mode="rb") as meta_data, spectral_file_path.open(mode="rb") as spectral_data:
            data_upload = UploadedFile(meta_data_file=django.core.files.File(meta_data,
                                                                             name=meta_data_path.name),
                                       spectral_data_file=django.core.files.File(spectral_data,
                                                                                 name=spectral_file_path.name))
            with pytest.raises(ValidationError, match="Patient ID mismatch."):
                data_upload.clean()

    def test_re_upload(self, django_db_blocker, observables, instruments, mock_data_from_files):
        n_patients = 10
        assert UploadedFile.objects.count() == 1
        assert Patient.objects.count() == n_patients
        assert Visit.objects.count() == n_patients

        with django_db_blocker.unblock():
            bulk_upload()

        assert UploadedFile.objects.count() == 2
        assert Patient.objects.count() == n_patients
        assert Visit.objects.count() == n_patients * 2

    def test_upload_on_cid(self, django_db_blocker, observables, instruments, mock_data_from_files):
        n_patients = 10
        assert UploadedFile.objects.count() == 1
        assert Patient.objects.count() == n_patients
        assert Visit.objects.count() == n_patients

        # copy patients but switch pid -> cid.
        new_patient_list = []
        old_pids = []
        for patient in Patient.objects.select_related("center").all():
            old_pids.append(patient.patient_id)
            new_patient_list.append(Patient(patient_cid=patient.patient_id,
                                            gender=patient.gender,
                                            center=patient.center))
            patient.delete()

        # Check old patients successfully deleted.
        assert Patient.objects.count() == 0
        assert Visit.objects.count() == 0

        for new_patient in new_patient_list:
            new_patient.full_clean()
            new_patient.save()
            # Check new patients definitely aren't the old ones.
            assert new_patient.patient_id not in old_pids

        assert Patient.objects.count() == n_patients
        assert Visit.objects.count() == 0

        # Re-ingest data.
        bulk_upload()

        assert UploadedFile.objects.count() == 2
        # If bulk_upload failed to detect the existing patients by CID, new patients would have been created instead
        # and Patient.objects.count() == n_patients * 2.
        assert Patient.objects.count() == n_patients
        assert Visit.objects.count() == n_patients


@pytest.mark.django_db(databases=["default", "bsr"])
def test_get_center(centers, mock_data_from_files):
    center = Center.objects.get(name="SSEC")
    assert get_center(center) is center

    from user.models import Center as UserCenter
    assert get_center(UserCenter.objects.get(pk=center.pk)) == center

    patient = Patient.objects.all()[0]
    patient.center = center
    patient.full_clean()
    patient.save()

    assert get_center(patient) is center

    for visit in patient.visit.all():
        assert get_center(visit) is center

    for bio_sample in visit.bio_sample.all():
        assert get_center(bio_sample) is center

    for spectral_data in bio_sample.spectral_data.all():
        assert get_center(spectral_data) is center

    for observation in Observation.objects.filter(visit__patient__center=center):
        assert get_center(observation) == center
        # assert get_center(observation.observable) is center  # TODO: Not yet related in observable.json fixture.
