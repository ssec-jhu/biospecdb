import pytest

from django.core.management import call_command
from django.db.utils import IntegrityError

from user.models import Center as UserCenter
from uploader.models import Center as UploaderCenter


@pytest.fixture(scope="function")
def centers(django_db_blocker):
    with django_db_blocker.unblock():
        call_command('loaddata', "centers")
        call_command("loaddata",  "--database=bsr", "centers")


@pytest.mark.django_db(databases=["default", "bsr"])
class TestCenters:
    def test_centers_fixture(self, centers):
        ssec_from_user_table = UserCenter.objects.get(name="SSEC")
        ssec_from_uploader_table = UploaderCenter.objects.get(name="SSEC")

        assert ssec_from_user_table.pk == ssec_from_uploader_table.pk
        assert ssec_from_user_table.name == ssec_from_uploader_table.name
        assert ssec_from_user_table.country == ssec_from_uploader_table.country

    def test_validation(self):
        UserCenter.objects.create(name="test", country="nowhere")
        with pytest.raises(IntegrityError, match="UNIQUE constraint failed:"):
            UserCenter.objects.create(name="test", country="nowhere")

    def test_save_replication(self):
        assert not UserCenter.objects.all()
        assert not UploaderCenter.objects.all()

        new_center = UserCenter(name="test", country="nowhere")
        new_center.full_clean()
        new_center.save()

        assert len(UserCenter.objects.all()) == 1
        assert len(UploaderCenter.objects.all()) == 1

        replica_center = UploaderCenter.objects.all()[0]

        assert new_center.pk == replica_center.pk
        assert new_center.name == replica_center.name
        assert new_center.country == replica_center.country

    def test_create_replication(self):
        """ Create doesn't call save()!!! """
        assert not UserCenter.objects.all()
        assert not UploaderCenter.objects.all()

        UserCenter.objects.create(name="test", country="nowhere")
        assert len(UserCenter.objects.all()) == 1
        # Create doesn't call save()!!!
        assert len(UploaderCenter.objects.all()) == 0

    def test_delete_replication(self, centers):
        assert len(UserCenter.objects.all()) == 2
        assert len(UploaderCenter.objects.all()) == 2

        for obj in UserCenter.objects.all():
            obj.delete()

        assert not UserCenter.objects.all()
        assert not UploaderCenter.objects.all()

    def test_bulk_delete_replication(self, centers):
        """ Bulk delete doesn't call delete()!!! """

        assert len(UserCenter.objects.all()) == 2
        assert len(UploaderCenter.objects.all()) == 2

        UserCenter.objects.all().delete()

        assert not UserCenter.objects.all()
        assert len(UploaderCenter.objects.all()) == 2

    def test_equivalence(self):
        user_center = UserCenter(name="test", country="nowhere")
        user_center.full_clean()
        user_center.save()

        uploader_center = UploaderCenter.objects.get(pk=user_center.pk)
        assert user_center == uploader_center
        assert uploader_center == user_center
