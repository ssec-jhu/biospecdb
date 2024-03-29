import datetime
import hashlib
import json
from pathlib import Path
import uuid
import zipfile

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MinLengthValidator
from django.db import models
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _

from biospecdb import __version__
from explorer.models import Query
from uploader.base_models import DatedModel


class CustomDjangoJsonEncoder(DjangoJSONEncoder):
    item_separator = ',\n'


def empty_list():
    return []


def get_app_version(*args, **kwargs):
    return str(__version__)


class Dataset(DatedModel):
    """ Model pre-canned dataset. """

    class Meta:
        verbose_name = "BSR dataset"
        get_latest_by = "updated_at"
        unique_together = [["name", "version"]]

    UPLOAD_DIR = "datasets/"  # MEDIA_ROOT/datasets

    # Cache objs.
    _file = None
    _filename = None

    id = models.UUIDField(unique=True, primary_key=True, default=uuid.uuid4, verbose_name="ID")
    query = models.ForeignKey(Query, on_delete=models.PROTECT, related_name="dataset")
    sql = models.TextField(blank=True, null=False, editable=False, verbose_name="SQL")
    version = models.CharField(max_length=32, null=False, blank=False, help_text="Version String, i.e., YYYY.N")
    name = models.CharField(max_length=32,
                            null=False,
                            blank=True,
                            help_text="If not provide the query title will be used")
    description = models.TextField(max_length=256,
                                   null=False,
                                   blank=True,
                                   help_text="If not provide the query description will be used")
    file = models.FileField(upload_to=UPLOAD_DIR,
                            editable=False,
                            null=False,
                            blank=True,
                            max_length=256)
    app_version = models.CharField(max_length=32,
                                   default=get_app_version,
                                   editable=False,
                                   null=False,
                                   blank=True,
                                   help_text="App version used to create data product")
    sha256 = models.CharField(max_length=64,
                              editable=False,
                              null=False,
                              blank=True,
                              verbose_name="SHA-256",
                              help_text="Checksum of downloadable file",
                              validators=[MinLengthValidator(64)])
    n_rows = models.IntegerField(null=False,
                                 blank=True,
                                 editable=False,
                                 help_text="Number of data rows")
    data_sha256 = models.CharField(max_length=64,
                                   editable=False,
                                   null=False,
                                   blank=True,
                                   verbose_name="Data SHA-256",
                                   help_text="Checksum of data table (not including any spectral data files).",
                                   validators=[MinLengthValidator(64)])
    spectral_data_filenames = models.JSONField(null=False,
                                               default=empty_list,
                                               blank=True,
                                               editable=False,
                                               help_text="List of spectral data filenames",
                                               encoder=CustomDjangoJsonEncoder)

    def __str__(self):
        return f"{self.name}_v{self.version}"

    def get_filename(self):
        return Path(str(self).replace('-', '_').replace('.', '_'))

    def clean(self, *args, **kwargs):
        self.name = self.name or self.query.title
        self.description = self.description or self.query.description
        self.sql = self.query.sql

        if not self.file:
            # Create file from query.
            file, info = self.execute_query()
            filename, n_rows, data_sha256, spectral_data_filenames = info

            if not n_rows:
                raise ValidationError(_("Query returned no data."))

            self._file = file
            self._filename = filename
            self.n_rows = n_rows
            self.data_sha256 = data_sha256
            self.spectral_data_filenames = spectral_data_filenames

        super().clean(*args, **kwargs)

    def get_exporter(self):
        return import_string(settings.DATASET_CATALOG_FILE_CLASS)

    def execute_query(self):
        exporter = self.get_exporter()(self.query)
        output, info = exporter.get_file_output(always_zip=True,
                                                include_data_files=True,
                                                return_info=True)

        ext = Path(exporter.get_filename()).suffix
        filename = self.get_filename().with_suffix(ext)
        return output, (filename, *info)

    def compute_checksum(self):
        if not self.file:
            return ''

        def _hash(fp):
            algorithm = hashlib.sha256()
            for chunk in fp.chunks():
                algorithm.update(chunk)
            return algorithm.hexdigest()

        if self.file.closed:
            with self.file.open() as fp:
                checksum = _hash(fp)
        else:
            # If already open, leave open, however, call open again to seek(0).
            self.file.open()
            checksum = _hash(self.file)
        return checksum

    def meta_info(self, **kwargs):
        info = dict(name=self.name,
                    version=self.version,
                    description=self.description,
                    sql=self.sql,
                    data_sha256=self.data_sha256,
                    app_version=self.app_version,
                    id=str(self.id),
                    n_rows=self.n_rows,
                    n_spectral_data_files=len(self.spectral_data_filenames),
                    timestamp=str(datetime.datetime.now()),
                    spectral_data_filenames=self.spectral_data_filenames)
        info.update(kwargs)
        return info

    def save(self, *args, **kwargs):
        if self._file:
            # Append dataset meta data as INFO.json.
            with zipfile.ZipFile(self._file,
                                 mode='a',
                                 compression=import_string(settings.ZIP_COMPRESSION),
                                 compresslevel=settings.ZIP_COMPRESSION_LEVEL) as archive:
                archive.writestr("INFO.json", json.dumps(self.meta_info(),
                                                         indent=1,
                                                         cls=DjangoJSONEncoder))
            self.file = File(self._file, name=self._filename)

        # Create checksum.
        self.sha256 = self.compute_checksum()

        # Save file (and everything else).
        super().save(*args, **kwargs)

    def asave(self, *args, **kwargs):
        raise NotImplementedError

    def delete(self, *args, delete_files=True, **kwargs):
        count, deleted = super().delete(*args, **kwargs)
        if count == 1:
            if delete_files:
                self.file.storage.delete(self.file.name)
        return count, deleted

    def adelete(self, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def get_orphan_files(cls):
        storage = cls.file.field.storage
        path = Path(cls.file.field.upload_to)
        # Collect all stored media files.
        try:
            fs_files = set([str(path / x) for x in storage.listdir(path)[1]])
        except FileNotFoundError:
            return storage, {}
        # Collect all media files referenced in the DB.
        data_files = set(x.file.name for x in cls.objects.all())
        # Compute orphaned file list.
        orphaned_files = fs_files - data_files
        return storage, orphaned_files
