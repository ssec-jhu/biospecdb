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

    file, ext = _handle_file_and_ext(file, ext=ext)

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
    cleaned_data = data.rename(columns=lambda x: x.lower())

    # TODO: Raise on null patient_id instead of silently dropping possible data.
    cleaned_data = cleaned_data.dropna(subset=['patient id'])

    # Insist on index as UUIDs.
    cleaned_data["patient id"] = cleaned_data["patient id"].map(lambda x: to_uuid(x))

    # Set index as "patient id" column.
    cleaned_data = cleaned_data.set_index("patient id")

    # Replace na & '' with None via na -> '' -> None
    cleaned_data = cleaned_data.fillna('').replace('', None)

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
    return pd.DataFrame({"wavelength": freqs, "intensity": specv},
                        index=[to_uuid(x) for x in cleaned_data["patient id"]])


def spectral_data_to_internal_file_format(file, patient_id, wavelengths, intensities):
    df = pd.DataFrame(dict(intensity=intensities), index=wavelengths).rename_axis("wavelength")

    patient_id_string = f"{spectral_data_to_internal_file_format.patient_id_string_prefix} {patient_id}\n"

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


spectral_data_to_internal_file_format.patient_id_string_prefix = f"# patient_id:"  # noqa: F541


def reset_file_cursor(file):
    if isinstance(file, django.core.files.File) and not file.closed:
        file.seek(0)


def spectral_data_from_internal_file_format(file):
    patient_id = read_patient_id_from_header(file)

    reset_file_cursor(file)
    data = pd.read_csv(file, header=1)

    return data, patient_id


def read_patient_id_from_header(file):
    def _open_and_read_header(filename):
        with open(filename) as f:
            return f.readline()

    if isinstance(file, django.core.files.File):
        if file.closed:
            header = _open_and_read_header(file.name)
        else:
            file.seek(0)
            header = file.readline()
            if isinstance(header, bytes):
                header = header.decode("utf-8")
    else:
        header = _open_and_read_header(file)

    header = header.split(':')
    if len(header) != 2:
        raise ValueError(f"Expected: '{spectral_data_to_internal_file_format.patient_id_string_prefix}' at 1st line of"
                         f"file: '{file}'")
    patient_id = to_uuid(header[1].strip())

    return patient_id


def read_individual_spectral_data(file, ext=None):
    """
        Read spectral data either from file path or IOStream.

        NOTE: `ext` is ignored when `file` is pathlike.

        There are two allowed input formats:
         * A single row of data following the same table format as expected for
          ``read_spectral_data_table()``, i.e., patient id column followed by a column for each sample wavelength value.
          This data format is supported in both .csv and .xlsx file formats.
         * A header line including "# patient_id:<ID>" followed by a table with two columns of wavelength and intensity,
          as is written out by ``spectral_data_to_csv()``. This data format is supported only by .csv file format (due
          to the need for header data).

        Irrespective of input data format this returns the latter, the tuple ``(df, patient_id)`` where ``df`` has only
        two columns: "wavelength" and "intensity".
    """

    file, ext = _handle_file_and_ext(file, ext=ext)

    try:
        df = read_spectral_data_table(file, ext=ext)
    except Exception:
        if FileFormats(ext) is FileFormats.XLSX:
            raise

        # NOTE: If the above fails assume it's of the other data format & .csv.

        patient_id = read_patient_id_from_header(file)

        # NOTE: This call ``read_csv()`` needs to be down here because:
        # Django seems to keep Files open, which can cause obvious (seek) issues when reading from the same file
        # multiple times. Rather than explicitly close the file for this specific read, we just read after the above
        # ``with`` automatically closes the file for us.
        data = pd.read_csv(file, header=1)
    else:
        if (n_patients := len(df.index)) > 1:
            raise ValueError(f"Expected spectral data file for just one patient but received table containing that for"
                             f"'{n_patients}' patients.")

        data = pd.DataFrame(dict(intensity=df["intensity"]), index=df["wavelength"]).rename_axis("wavelength")
        patient_id = data.index[0]

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
    spectral_data_to_internal_file_format(file=filename, patient_id=patient_id, wavelengths=wavelengths, intensities=intensities)
    return filename, patient_id


def get_file_info(file_wrapper):
    """ The actual file buffer is nested at different levels depending on container class. """
    if isinstance(file_wrapper, (django.core.files.uploadedfile.TemporaryUploadedFile,
                                 django.core.files.uploadedfile.InMemoryUploadedFile)):
        file = file_wrapper.file.file
    elif isinstance(file_wrapper, django.core.files.File):
        file = file_wrapper.file
    else:
        raise NotImplementedError(type(file_wrapper))
    return file, Path(file_wrapper.name).suffix


def _handle_file_and_ext(file, ext=None):
    # TODO: Is this too similar to ``get_file_info``?
    if isinstance(file, (IOBase, django.core.files.File)):
        # In this mode the ext must be given as it can't be determined from a file path, since one isn't given.
        if ext:
            ext = ext.lower()
        else:
            raise ValueError(f"When passing an IO stream, ext must be specified as one of '{FileFormats.list()}'.")
    else:
        file = Path(file)
        ext = file.suffix.lower()

    return file, ext


def to_uuid(value):
    if isinstance(value, UUID):
        return value

    if value is None:
        return

    def _to_uuid(value):
        # This implementation was copied from django.db.models.UUIDField.to_python.
        input_form = "int" if isinstance(value, int) else "hex"
        return UUID(**{input_form: value})

    try:
        # NOTE: Since string representations of UUIDs containing only numerics are 100% valid, give these precedence by
        # trying to convert directly to UUID instead of converting to int first - try the int route afterward.
        return _to_uuid(value)
    except ValueError as error_0:
        if not isinstance(value, str):
            raise

        # Value could be, e.g., '2', so try converting to int.
        try:
            return _to_uuid(int(value))
        except ValueError as error_1:
            raise error_1 from error_0


def is_valid_uuid(value):
    # This implementation was copied from django.db.models.UUIDField.to_python.
    if value is not None and not isinstance(value, UUID):
        try:
            to_uuid(value)
        except (AttributeError, ValueError):
            False
    return True
