from datetime import datetime
import enum
import importlib
from io import IOBase, StringIO
import os
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pandas as pd

import django.core.files
import django.core.files.uploadedfile

from . import __project__  # Keep as relative for templating reasons.


# Values used when mocking spectral data.
SPECTRAL_DATA_MAX_WAVELENGTH = 4000
SPECTRAL_DATA_MIN_WAVELENGTH = 651
SPECTRAL_DATA_N_BINS = 1798


def find_package_location(package=__project__):
    return importlib.util.find_spec(package).submodule_search_locations[0]


def find_repo_location(package=__project__):
    return os.path.abspath(os.path.join(find_package_location(package), os.pardir))


class StrEnum(enum.StrEnum):
    @classmethod
    def list(cls):
        return [x.value for x in cls]


class FileFormats(StrEnum):
    CSV = ".csv"
    XLSX = ".xlsx"

    @classmethod
    def choices(cls):
        return [x.value.replace('.', '') for x in cls]  # Remove '.' for django validator.


def read_raw_data(file, ext=None):
    """
    Read data either from file path or IOStream.

    NOTE: `ext` is ignored when `file` is pathlike.
    """

    if isinstance(file, (IOBase, django.core.files.File)):
        # In this mode the ext must be given as it can't be determined from a file path, since one isn't given.
        if ext:
            ext = ext.lower()
        else:
            raise ValueError(f"When passing an IO stream, ext must be specified as one of '{FileFormats.list()}'.")
    else:
        file = Path(file)
        ext = file.suffix.lower()

    kwargs = dict(true_values=["yes", "Yes"],  # In addition to case-insensitive variants of True.
                  false_values=["no", "No"],  # In addition to case-insensitive variants of False.
                  na_values=[' ', "unknown", "Unknown", "na", "none"]
                  )
    # NOTE: The following default na_values are also used:
    # ‘’, ‘  # N/A’, ‘#N/A N/A’, ‘#NA’, ‘-1.#IND’, ‘-1.#QNAN’, ‘-NaN’, ‘-nan’, ‘1.#IND’, ‘1.#QNAN’, ‘<NA>’, ‘N/A’, ‘NA’,
    # ‘NULL’, ‘NaN’, ‘None’, ‘n/a’, ‘nan’, ‘null’.

    # NOTE: When the file size is > 2.5M Django will chunk and this will need to be handled. See
    # https://github.com/ssec-jhu/biospecdb/issues/38
    if ext == FileFormats.CSV:
        data = pd.read_csv(file, **kwargs)
    elif ext == FileFormats.XLSX:
        data = pd.read_excel(file, **kwargs)
    else:
        raise NotImplementedError(f"File ext must be one of {FileFormats.list()} not '{ext}'.")

    return data


def read_meta_data(file, ext=None):
    data = read_raw_data(file, ext=ext)

    # Clean.
    # TODO: Raise on null patient_id instead of silently dropping possible data.
    cleaned_data = data.rename(columns=lambda x: x.lower()) \
        .dropna(subset=['patient id']) \
        .set_index('patient id') \
        .fillna('').replace('', None)
    return cleaned_data


def read_spectral_data_table(file, ext=None):
    data = read_raw_data(file, ext=ext)

    # Clean.
    # TODO: Raise on null patient id instead of silently dropping possible data.
    cleaned_data = data.rename(columns={"PATIENT ID": "patient id"})
    spec_only = cleaned_data.drop(columns=["patient id"], inplace=False)
    wavelengths = spec_only.columns.tolist()
    specv = spec_only.values.tolist()
    freqs = [wavelengths for i in range(len(specv))]
    return pd.DataFrame({"wavelength": freqs, "intensity": specv}, index=cleaned_data["patient id"])


def spectral_data_to_csv(file, patient_id, wavelengths, intensities):
    df = pd.DataFrame(dict(intensity=intensities), index=wavelengths).rename_axis("wavelength")

    patient_id_string = f"{spectral_data_to_csv.patient_id_string_prefix} {patient_id}\n"

    if file is None:
        # Creat str buffer, write to it, then return its contents.
        with StringIO() as f:
            f.write(patient_id_string)
            df.to_csv(f)
            return f.getvalue()
    else:
        if isinstance(file, django.core.files.File):
            file = file.name

        with open(file, mode='w') as f:
            f.write(patient_id_string)
            df.to_csv(f)


spectral_data_to_csv.patient_id_string_prefix = f"# patient_id:"  # noqa: F541


def spectral_data_from_csv(filename):
    if isinstance(filename, django.core.files.File):
        filename = filename.name

    with open(filename) as f:
        patient_id = f.readline().split(":")

    if len(patient_id) != 2:
        raise ValueError(f"Expected: '{spectral_data_to_csv.patient_id_string_prefix }' at 1st line of file:"
                         f"'{filename}'")

    patient_id = patient_id[1].strip()

    # NOTE: This call ``read_csv()`` needs to be down here because:
    # Django seems to keep Files open, which can cause obvious (seek) issues when reading from the same file
    # multiple times. Rather than explicitly close the file for this specific read, we just read after the above
    # ``with`` automatically closes the file for us.
    data = pd.read_csv(filename, header=1)

    return data, patient_id


def to_bool(value):
    TRUE = ("true", "yes", True)
    FALSE = ("false", "no", False)

    if value is None or value == '':
        return None

    if isinstance(value, str):
        value = value.lower()

    if value in TRUE:
        return True
    elif value in FALSE:
        return False
    else:
        if isinstance(value, (int, float)):
            raise ValueError(f"int|float casts to bool must have explicit values of 0|1 (inc. their flt equivalents.), "
                             f"not '{value}'")
        else:
            raise ValueError(f"Bool aliases are '{TRUE}|{FALSE}', not '{value}'")


def mock_bulk_spectral_data(path=Path.home(),
                            max_wavelength=SPECTRAL_DATA_MAX_WAVELENGTH,
                            min_wavelength=SPECTRAL_DATA_MIN_WAVELENGTH,
                            n_bins=SPECTRAL_DATA_N_BINS,
                            n_patients=10):
    path = Path(path)
    data = pd.DataFrame(data=np.random.rand(n_patients, n_bins),
                        columns=np.arange(max_wavelength, min_wavelength, (min_wavelength - max_wavelength) / n_bins),
                        index=[uuid4() for i in range(n_patients)])
    data.index.name = "PATIENT ID"
    # data.index += 1  # Make index 1 based.

    filenames = (path / "spectral_data.xlsx", path / "spectral_data.csv")
    data.to_excel(filenames[0])
    data.to_csv(filenames[1])

    return data, filenames


def mock_single_spectral_data_file(path=Path.home(),
                                   patient_id=uuid4(),
                                   max_wavelength=SPECTRAL_DATA_MAX_WAVELENGTH,
                                   min_wavelength=SPECTRAL_DATA_MIN_WAVELENGTH,
                                   n_bins=SPECTRAL_DATA_N_BINS):
    path = Path(path)
    wavelengths = np.arange(max_wavelength, min_wavelength, (min_wavelength - max_wavelength) / n_bins)
    intensities = np.random.rand(n_bins)
    filename = path / datetime.now().strftime("%m-%d-%Y-%H-%M")
    filename = filename.with_suffix(".csv")
    spectral_data_to_csv(file=filename, patient_id=patient_id, wavelengths=wavelengths, intensities=intensities)
    return filename, patient_id


def get_file_info(file_wrapper):
    """ The actual file buffer is nested at different levels depending on container class. """
    if isinstance(file_wrapper, django.core.files.uploadedfile.TemporaryUploadedFile):
        file = file_wrapper.file.file
    elif isinstance(file_wrapper, django.core.files.File):
        file = file_wrapper.file
    else:
        raise NotImplementedError(type(file_wrapper))
    return file, Path(file_wrapper.name).suffix


def is_valid_uuid(value):
    # This implementation was copied from django.db.models.UUIDField.to_python.
    if value is not None and not isinstance(value, UUID):
        input_form = "int" if isinstance(value, int) else "hex"
        try:
            return UUID(**{input_form: value})
        except (AttributeError, ValueError):
            False
    return True
