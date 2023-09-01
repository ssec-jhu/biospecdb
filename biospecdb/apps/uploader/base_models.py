from django.db import models, transaction
from django.utils.module_loading import import_string

from uploader.sql import drop_view, update_view


class TextChoices(models.TextChoices):
    @classmethod
    def _missing_(cls, value):
        if not isinstance(value, str):
            return

        for item in cls:
            if value.lower() in (item.name.lower(),
                                 item.label.lower(),
                                 item.value.lower(),
                                 item.name.lower().replace('_', '-'),
                                 item.label.lower().replace('_', '-'),
                                 item.value.lower().replace('_', '-')):
                return item


class SqlView:
    sql_view_dependencies = tuple()

    # TODO: Add functionality to auto create own view if doesn't already exist.

    @classmethod
    def sql(cls):
        """ Returns the SQL string and an optional list of params used in string. """
        raise NotImplementedError

    @classmethod
    def drop_view(cls, *args, **kwargs):
        return drop_view(cls._meta.db_table, *args, **kwargs)

    @classmethod
    @transaction.atomic
    def update_view(cls, *args, **kwargs):
        """ Update view and view dependencies.

            NOTE: This func is transactional such that all views are updated or non are. However, also note that this
                  can result in the views being rolled back to, being stale and outdated (depending on the cause of the
                  update).
        """
        for view_dependency in cls.sql_view_dependencies:
            view_dependency.update_view()

        sql, params = cls.sql()
        return update_view(cls._meta.db_table, sql, *args, params=params, **kwargs)


class ModelWithViewDependency(models.Model):
    class Meta:
        abstract = True

    sql_view_dependencies = None

    @transaction.atomic
    def save(self, *args, update_view=True, **kwargs):
        super().save(*args, **kwargs)

        if update_view and self.sql_view_dependencies:
            for sql_view in self.sql_view_dependencies:
                if isinstance(sql_view, str):
                    sql_view = import_string(sql_view)
                sql_view.update_view()

    def asave(self, *args, **kwargs):
        raise NotImplementedError("See https://github.com/ssec-jhu/biospecdb/issues/66")