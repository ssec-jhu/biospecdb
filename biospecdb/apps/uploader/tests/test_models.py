from uuid import uuid4

from django.core.exceptions import ValidationError
import django.core.files
from django.db.utils import IntegrityError
import pytest

import biospecdb.util
from uploader.models import BioSample, Disease, Instrument, Patient, SpectralData, Symptom, Visit, UploadedFile
from uploader.loaddata import save_data_to_db

import biospecdb.util
from conftest import DATA_PATH


class TestPatient:
    def test_creation(self, db):
        Patient(gender=Patient.Gender.MALE).full_clean()
        Patient(gender=Patient.Gender.FEMALE).full_clean()

    def test_db_creation(self, db):
        Patient.objects.create(gender=Patient.Gender.MALE).full_clean()
        Patient.objects.create(gender=Patient.Gender.FEMALE).full_clean()

        assert len(Patient.objects.all()) == 2

        Patient.objects.create(gender=Patient.Gender.MALE).full_clean()
        assert len(Patient.objects.all()) == 3

        males = Patient.objects.filter(gender=Patient.Gender.MALE)
        females = Patient.objects.filter(gender=Patient.Gender.FEMALE)

        assert len(males) == 2
        assert len(females) == 1

        assert males[0].patient_id != males[1].patient_id

    def test_short_name(self, db):
        patient = Patient(gender=Patient.Gender.MALE)
        patient.full_clean()
        assert patient.short_id() in str(patient)

    def test_gender_validation(self, db):
        Patient(gender=Patient.Gender.MALE).full_clean()

        with pytest.raises(ValidationError):
            Patient(gender="blah").full_clean()

    def test_fixture_data(self, db, patients):
        assert len(Patient.objects.all()) == 3
        assert Patient.objects.get(pk="437de0d7-6618-4445-bab2-03822310b0ef")

    def test_editable_patient_id(self, db):
        patient_id = uuid4()
        Patient.objects.create(patient_id=patient_id, gender=Patient.Gender.FEMALE)
        assert Patient.objects.get(pk=patient_id)


class TestVisit:
    def test_visit_number(self, db, visits):
        assert Visit.objects.get(pk=1).visit_number == 1
        assert Visit.objects.get(pk=3).visit_number == 2

    def test_walk(self, db, visits):
        v1 = Visit.objects.get(pk=1)
        v2 = Visit.objects.get(pk=3)
        assert v1.patient.pk == v2.patient.pk

    def test_previous_visit_same_patient_validation(self, db, visits):
        visit = Visit.objects.get(pk=2)
        visit.previous_visit = Visit.objects.get(pk=1)
        with pytest.raises(ValidationError):
            visit.full_clean()

    def test_previous_visit_patient_age_validation(self, db, visits):
        previous_visit = Visit.objects.get(pk=1)
        visit = Visit(patient=previous_visit.patient,
                      previous_visit=previous_visit,
                      patient_age=previous_visit.patient_age - 1)
        with pytest.raises(ValidationError, match="Previous visit must NOT be older than this one"):
            visit.full_clean()

    def test_circular_previous_visit(self, db, visits):
        visit = Visit.objects.get(pk=1)
        visit.previous_visit = visit
        with pytest.raises(ValidationError, match="Previous visit cannot not be this current visit"):
            visit.full_clean()


class TestDisease:
    def test_fixture_data(self, db, diseases):
        disease = Disease.objects.get(pk=1)
        assert disease.name == "Ct_gene_N"
        assert disease.value_class == Disease.Types.FLOAT

    def test_name_uniqueness(self, db):
        Disease.objects.create(name="A", description="blah", alias="a")
        with pytest.raises(IntegrityError, match="unique_disease_name"):
            Disease.objects.create(name="a", description="blah", alias="b")

    def test_alias_uniqueness(self, db):
        Disease.objects.create(name="A", description="blah", alias="a")
        with pytest.raises(IntegrityError, match="unique_alias_name"):
            Disease.objects.create(name="b", description="blah", alias="A")


class TestInstrument:
    def test_fixture_data(self, db, instruments):
        instrument = Instrument.objects.get(pk=1)
        assert instrument.spectrometer == "AGILENT_CORY_630"
        assert instrument.atr_crystal == "ZNSE"


class TestSymptom:
    def test_days_symptomatic_validation(self, db, diseases, visits):
        visit = Visit.objects.get(pk=1)
        age = visit.patient_age
        symptom = Symptom.objects.create(visit=visit,
                                         disease=Disease.objects.get(name="fever"),
                                         days_symptomatic=age * 365 + 1)
        with pytest.raises(ValidationError):
            symptom.full_clean()

    def test_disease_value_validation(self, db, diseases, visits):
        symptom = Symptom.objects.create(visit=Visit.objects.get(pk=1),
                                         disease=Disease.objects.get(name="Ct_gene_N"),
                                         days_symptomatic=7,
                                         disease_value="strings can't cast to floats")
        with pytest.raises(ValidationError):
            symptom.full_clean()

    @pytest.mark.parametrize("value", (True, False))
    def test_disease_value_bool_cast(self, db, diseases, visits, value):
        symptom = Symptom.objects.create(visit=Visit.objects.get(pk=1),
                                         disease=Disease.objects.get(name="fever"),
                                         days_symptomatic=7,
                                         disease_value=str(value))
        symptom.full_clean()
        assert symptom.disease_value is value


class TestBioSample:
    ...


class TestSpectralData:
    ...


class TestUploadedFile:
    @pytest.mark.parametrize("file_ext", UploadedFile.FileFormats.list())
    def test_upload_without_error(self, db, diseases, instruments, file_ext):
        meta_data_path = (DATA_PATH/"meta_data").with_suffix(file_ext)
        spectral_file_path = (DATA_PATH / "spectral_data").with_suffix(file_ext)
        with meta_data_path.open(mode="rb") as meta_data, spectral_file_path.open(mode="rb") as spectral_data:
            data_upload = UploadedFile(meta_data_file=django.core.files.File(meta_data,
                                                                             name=meta_data_path.name),
                                       spectral_data_file=django.core.files.File(spectral_data,
                                                                                 name=spectral_file_path.name))
            data_upload.clean()
            data_upload.save()

    def test_mock_data_from_files_fixture(self, mock_data_from_files):
        n_patients = 10
        assert len(UploadedFile.objects.all()) == 1
        assert len(Patient.objects.all()) == n_patients
        assert len(Visit.objects.all()) == n_patients
        assert len(BioSample.objects.all()) == n_patients
        assert len(SpectralData.objects.all()) == n_patients

    def test_mock_data_fixture(self, mock_data):
        n_patients = 10
        assert len(Patient.objects.all()) == n_patients
        assert len(Visit.objects.all()) == n_patients
        assert len(BioSample.objects.all()) == n_patients
        assert len(SpectralData.objects.all()) == n_patients

    def test_number_symptoms(self, db, diseases, instruments):
        """ The total number of symptoms := N_patients * N_diseases. """
        assert len(Patient.objects.all()) == 0  # Assert empty.

        save_data_to_db(DATA_PATH / "meta_data.csv",
                        DATA_PATH / "spectral_data.csv")

        n_patients = len(Patient.objects.all())
        n_diseases = len(Disease.objects.all())
        n_symptoms = len(Symptom.objects.all())

        # Assert not empty.
        assert n_patients > 0
        assert n_diseases > 0
        assert n_symptoms > 0

        # When Covid_RT_qPCR is negative both Ct_gene_N & Ct_gene_ORF1ab symptoms will be null and omitted. This must be
        # accounted for in the total.
        n_empty_covid_symptoms = len((Symptom.objects.filter(disease=Disease.objects.get(name="Covid_RT_qPCR")))
                                     .filter(disease_value="Negative"))
        assert n_symptoms == n_patients * n_diseases - n_empty_covid_symptoms * 2

    def test_days_of_symptoms(self, mock_data_from_files):
        week_long_symptoms = Symptom.objects.filter(days_symptomatic=7)
        assert len(week_long_symptoms) > 1
        assert week_long_symptoms[0].days_symptomatic == 7
        null_days = len(Symptom.objects.filter(days_symptomatic=None))
        assert null_days > 1
        assert null_days < len(Symptom.objects.all())

    @pytest.mark.parametrize("file_ext", UploadedFile.FileFormats.list())
    def test_patient_ids(self, mock_data_from_files, file_ext):
        meta_data_path = (DATA_PATH / "meta_data").with_suffix(file_ext)
        df = biospecdb.util.read_meta_data(meta_data_path)

        all_patients = Patient.objects.all()

        assert len(all_patients) == len(df)
        for index in df.index:
            assert all_patients.get(pk=index)

    def test_patient_id_validation(self, tmp_path, db, diseases, django_db_blocker, instruments):
        meta_data_path = (DATA_PATH / "meta_data").with_suffix(UploadedFile.FileFormats.XLSX)
        n_patients = len(biospecdb.util.read_meta_data(meta_data_path).index)

        # Generate a new spectral data file with patient IDs different from that in meta_data_path.
        _data, filenames = biospecdb.util.mock_bulk_spectral_data(path=tmp_path, n_patients=n_patients)
        spectral_file_path = filenames[0]

        with django_db_blocker.unblock():
            with meta_data_path.open(mode="rb") as meta_data:
                with spectral_file_path.open(mode="rb") as spectral_data:
                    data_upload = UploadedFile(meta_data_file=django.core.files.File(meta_data,
                                                                                     name=meta_data_path.name),
                                               spectral_data_file=django.core.files.File(spectral_data,
                                                                                         name=spectral_file_path))
                    with pytest.raises(ValidationError, match="Patient ID mismatch"):
                        data_upload.clean()
