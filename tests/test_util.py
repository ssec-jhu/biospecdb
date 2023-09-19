from uuid import uuid4

import pytest

import biospecdb.util
from biospecdb.util import find_package_location, find_repo_location, mock_single_spectral_data_file,\
    read_individual_spectral_data
from biospecdb import __project__, __version__


def test_version():
    assert __version__


def test_project():
    assert __project__


def test_find_package_location():
    assert find_package_location()


def test_find_repo_location():
    assert find_repo_location()


def test_mock_bulk_spectral_data(tmp_path):
    n_patients = 10
    data, filenames = biospecdb.util.mock_bulk_spectral_data(path=tmp_path,
                                                             n_patients=n_patients)
    assert len(filenames) == 2
    assert data.shape == (n_patients, biospecdb.util.SPECTRAL_DATA_N_BINS)
    for idx in data.index:
        biospecdb.util.is_valid_uuid(idx)


def test_mock_single_spectral_data_file(tmp_path):
    patient_id = uuid4()
    filename, _patient_id = mock_single_spectral_data_file(path=tmp_path, patient_id=patient_id)
    data, patient_id_from_file = read_individual_spectral_data(filename)
    assert patient_id == patient_id_from_file
    assert data.shape == (biospecdb.util.SPECTRAL_DATA_N_BINS, 2)
    assert set(data.columns) == {"wavelength", "intensity"}
    assert data["wavelength"].max() == biospecdb.util.SPECTRAL_DATA_MAX_WAVELENGTH
    step_size = (biospecdb.util.SPECTRAL_DATA_MIN_WAVELENGTH - biospecdb.util.SPECTRAL_DATA_MAX_WAVELENGTH) /\
                biospecdb.util.SPECTRAL_DATA_N_BINS
    assert pytest.approx(data["wavelength"].min() + step_size) == biospecdb.util.SPECTRAL_DATA_MIN_WAVELENGTH


def test_spectral_data_pytest_fixture(spectral_data):
    filename, patient_id = spectral_data
    data, patient_id_from_file = read_individual_spectral_data(filename)
    assert patient_id == patient_id_from_file
