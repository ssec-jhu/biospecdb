import pytest

from django.db.utils import OperationalError

from uploader.models import Observable, FullPatientView, ObservationsView, VisitObservationsView, Observation
from uploader.sql import execute_sql


@pytest.mark.django_db(databases=["default", "bsr"])
class TestViews:
    def test_observations_view(self, mock_data):
        all_view_data = ObservationsView.update_view(check=True, limit=None)
        all_observations = Observation.objects.all()
        assert len(all_observations) > 1  # Check non-empty.
        assert len(all_view_data) == len(all_observations)

    def test_observations_view_django_model(self, mock_data):
        all_view_data = ObservationsView.update_view(limit=None)
        all_django_view_data = ObservationsView.objects.all()
        assert len(all_view_data) > 1  # Check non-empty.
        assert len(all_view_data) == len(all_django_view_data)

    def test_django_raise_on_missing_view(self, mock_data):
        ObservationsView.drop_view()
        with pytest.raises(OperationalError, match="no such table:"):
            # NOTE: Django ORM queries are lazy, so we call exists() instead of all() as the latter is lazy.
            ObservationsView.objects.exists()

    def test_visit_observations_view(self, mock_data):
        VisitObservationsView.update_view(check=True)

    def test_full_patient_view(self, mock_data):
        FullPatientView.update_view(check=True)

    def test_view_dependencies(self, mock_data):
        ObservationsView.drop_view()
        with pytest.raises(OperationalError, match="no such table:"):
            ObservationsView.objects.exists()

        VisitObservationsView.drop_view()
        with pytest.raises(OperationalError, match="no such table:"):
            VisitObservationsView.objects.exists()

        # This view should create its view dependencies which are the two above.
        FullPatientView.update_view()

        ObservationsView.objects.exists()
        VisitObservationsView.objects.exists()
        FullPatientView.objects.exists()

    def test_view_caching(self, mock_data):
        """
            FullPatientView depends on VisitObservationsView, if VisitObservationsView is updated does FullPatientView
            see the updated view or does it point to some older cached/inlined view?
            With sqlite, it sees the newer updated view, but we should test to help us detect otherwise if we change the
            DB backend.
        """

        FullPatientView.update_view()

        # Sanity check that the new observable does not exist.
        with pytest.raises(OperationalError, match="no such column:"):
            execute_sql(f"select my_new_observable from {FullPatientView._meta.db_table}", db=FullPatientView.db)

        # Add new observable.
        observable = Observable(name="my_new_observable", category=Observable.Category.COMORBIDITY)
        observable.clean()
        observable.save(update_view=False)

        # Sanity check it still doesn't exist without ANY view update.
        with pytest.raises(OperationalError, match="no such column:"):
            execute_sql(f"select my_new_observable from {FullPatientView._meta.db_table}", db=FullPatientView.db)

        # Update view dependency
        FullPatientView.sql_view_dependencies[0].update_view()

        # Assert that new observable exists without having updated actual view.
        execute_sql(f"select my_new_observable from {FullPatientView._meta.db_table}", db=FullPatientView.db)

    def test_view_update_on_observable_save(self, mock_data):
        FullPatientView.update_view()

        # Sanity check that the new observable does not exist.
        with pytest.raises(OperationalError, match="no such column:"):
            execute_sql(f"select my_new_observable from {FullPatientView._meta.db_table}", db=FullPatientView.db)

        # Add new observable.
        Observable.objects.create(name="my_new_observable", category=Observable.Category.SYMPTOM)

        # Assert that new observable exists without having updated actual view.
        execute_sql(f"select my_new_observable from {FullPatientView._meta.db_table}", db=FullPatientView.db)

    def test_update_sql_views_command(self, mock_data, sql_views):
        resp = execute_sql(f"select * from {FullPatientView._meta.db_table}", db=FullPatientView.db)
        assert len(resp) == 10
