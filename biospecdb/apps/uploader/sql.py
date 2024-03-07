import re

from django.core.cache import cache
from django.core.exceptions import SuspiciousOperation
from django.db import connection, connections, transaction
from django.db.utils import OperationalError, ProgrammingError

from explorer.schema import connection_schema_cache_key


def secure_name(name):
    if re.search(r"[^_a-zA-Z0-9]", name):
        raise SuspiciousOperation(f"SQL security issue! Expected name consisting of only [_a-zA-Z] but got '{name}'")


def execute_sql(sql, db=None, params=None):
    con = connections[db] if db else connection
    with con.cursor() as cursor:
        cursor.execute(sql, params=params)

        try:
            if result := cursor.fetchall():
                columns = [col[0] for col in cursor.description]
                return [dict(zip(columns, row)) for row in result]
        except ProgrammingError as error:
            # With postgres, fetchall() raises rather than returning None (seems like a bug).
            if "the last operation didn't produce a result" in str(error) or "no result available" in str(error):
                pass
            else:
                raise


def drop_view(view, db=None):
    secure_name(view)
    try:
        execute_sql(f"drop view {view}", db=db)  # nosec B608
    except OperationalError as error:
        if "no such view:" not in str(error):
            raise
    except ProgrammingError as error:
        if "does not exist" not in str(error):
            raise


def update_view(view, sql, db=None, params=None, check=True, limit=1):
    """ SQLite can't alter views, so they must first be dropped and then re-added. """
    # django-sql-explorer caches schemas, so invalidate entries to trigger schema rebuild.
    key = connection_schema_cache_key(db)
    cache.delete(key)  # Doesn't raise.

    secure_name(view)

    if connection.vendor == "postgresql":
        sql = sql.lower().replace("create", "create or replace")
        return create_view(view, sql, db=db, params=params, check=check, limit=limit)
    elif connection.vendor == "sqlite":
        # SQLite has no view replace/alter functionality so we must first drop the view and then re-add it.
        # NOTE: create_view() is transactional around creating the view and then checking its correctness, however,
        # we don't include the drop within the transaction. If the view requires updating but fails, it seems safer to
        # have no view rather than potentially blindly (to a user) rolling back to the outdated view.
        # If this behaviour isn't desired, ensure that whatever triggers the need for an update (the caller) is also
        # transactional around the DB update and this call, e.g., see ``uploader.base_models.ModelWithViewDependency.save``.
        # That way the old view _will_ be rolled back if the below check fails but so will the cause of update such that the
        # view is still correct for the rolled back DB state.
        # This behaviour also facilitates trivial testing.
        drop_view(view, db=db)
        return create_view(view, sql, db=db, params=params, check=check, limit=limit)
    else:
        # Note: This may not be necessarily true, but test view correctness against vendor and explicitly add to the
        # above.
        raise NotImplementedError


def create_view(view, sql, db=None, params=None, check=True, limit=1):
    with transaction.atomic(using="bsr"):
        execute_sql(sql, db=db, params=params)

        # The view isn't actually used upon creation so may contain latent errors. To check for errors, we query it so
        # that it complains upon creation not later upon usage.
        if check:
            sql = f"select * from {view}"  # nosec B608
            params = []
            if limit:
                sql += " limit %s"
                params.append(limit)
            return execute_sql(sql, db=db, params=params)
