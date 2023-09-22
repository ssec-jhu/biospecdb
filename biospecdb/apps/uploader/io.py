from io import IOBase
from pathlib import Path

import django.core.files
from django.core.files.storage import FileSystemStorage
import django.core.files.uploadedfile
from django.utils.deconstruct import deconstructible
import pandas as pd

from biospecdb.util import StrEnum, to_uuid


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
                  na_values=[' ', "unknown", "Unknown", "na", "none"],
                  dtype={"Patient ID":  str, "patient id": str, "patient_id": str})
    # NOTE: The patient ID as a str is crucial for converting to UUIDs as floats cannot be safely converted nor is it
    # ok to read in as int as they could be actual UUID str.
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

    # Set index as "patient id" column.
    cleaned_data = cleaned_data.set_index("patient id")

    # Insist on index as UUIDs.
    cleaned_data = cleaned_data.set_index(cleaned_data.index.map(lambda x: to_uuid(x)))

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


def spectral_data_to_csv(file, wavelengths, intensities):
    return pd.DataFrame(dict(intensity=intensities), index=wavelengths).rename_axis("wavelength").to_csv(file)


def spectral_data_from_csv(filename):
    return pd.read_csv(filename)


def get_file_info(file_wrapper):
    """ The actual file buffer is nested at different levels depending on container class. """
    if isinstance(file_wrapper, django.core.files.uploadedfile.TemporaryUploadedFile):
        file = file_wrapper.file.file
    elif isinstance(file_wrapper, django.core.files.File):
        file = file_wrapper.file
    else:
        raise NotImplementedError(type(file_wrapper))

    # The file may have already been read but is still open - so rewind. TODO: potential conflict with #38?
    if hasattr(file, "closed") and not file.closed and hasattr(file, "seek"):
        file.seek(0)
    return file, Path(file_wrapper.name).suffix


@deconstructible(path="biospecdb.apps.uploader.io.SpectralDataFileStorage")
class SpectralDataFileStorage(FileSystemStorage):
    def _save(self, name, content):
        saved_file_path = super()._save(name, content)
        return saved_file_path
