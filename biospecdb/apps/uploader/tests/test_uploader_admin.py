from inspect import getmembers

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import models
from django.test import Client
import pytest

from user.models import BaseCenter, Center as UserCenter
from uploader.base_models import DatedModel, SqlView, ModelWithViewDependency
import uploader.models


User = get_user_model()

SKIP_MODELS = [uploader.models.BioSampleType, uploader.models.SpectraMeasurementType]


uploader_models = []
for name, obj in getmembers(uploader.models):
    if isinstance(obj, type)\
            and issubclass(obj, models.Model)\
            and not issubclass(obj, (SqlView, BaseCenter)) \
            and obj not in (BaseCenter, DatedModel, ModelWithViewDependency, SqlView):
        uploader_models.append(obj)


def add_model_perms(user, model=None, action=None):
    if model:
        if action is None:
            raise NotImplementedError("action must be specified.")
        perm = Permission.objects.get(codename=f"{action}_{model}")
        user.user_permissions.add(perm)
    else:
        for perm in Permission.objects.all():
            for obj in uploader_models:
                if obj.__name__.lower() in perm.codename:
                    if action:
                        if action in perm.codename:
                            user.user_permissions.add(perm)
                    else:
                        user.user_permissions.add(perm)
    user.save()
    return user


@pytest.fixture()
def staffuser(centers):
    user = User.objects.create(username="staff",
                               email="staff@jhu.edu",
                               password="secret",
                               center=UserCenter.objects.get(name="SSEC"),
                               is_staff=True,
                               is_superuser=False)
    return user


@pytest.fixture()
def superuser(centers):
    return User.objects.create(username="admin",
                               email="admin@jhu.edu",
                               password="secret",
                               center=UserCenter.objects.get(name="SSEC"),
                               is_staff=True,
                               is_superuser=True)


@pytest.mark.django_db(databases=["default", "bsr"])
class TestAdminPage:
    @pytest.mark.parametrize("user", ("staffuser", "superuser"))
    @pytest.mark.parametrize("url_root", ("/data/uploader/", "/admin/uploader/"))
    @pytest.mark.parametrize("action", ('/', "/add/"))
    @pytest.mark.parametrize("model", uploader_models)
    def test_admin_pages(self, request, user, url_root, model, action):
        user = request.getfixturevalue(user)

        if url_root == "/data/uploader/" and model in SKIP_MODELS:
            pytest.skip("Model not registered with data admin site.")

        if url_root == "/admin/uploader/" and not user.is_superuser:
            pytest.skip("Admin site restricted to superuser.")

        if model in SKIP_MODELS and not user.is_superuser:
            pytest.skip("Model edits restricted to superuser")

        c = Client()
        if not user.is_superuser:
            add_model_perms(user)  # Grant blanket perms to everything.
        c.force_login(user)
        response = c.get(f"{url_root}{model.__name__.lower()}{action}", follow=False)
        assert response.status_code == 200

    @pytest.mark.parametrize("with_perm", (True, False))
    @pytest.mark.parametrize("url_root", ("/data/uploader/", "/admin/uploader/"))
    @pytest.mark.parametrize("model", uploader_models)
    def test_admin_view_perms_pages(self, with_perm, staffuser, url_root, model, mock_data):
        if url_root == "/data/uploader/" and model in SKIP_MODELS:
            pytest.skip("Model not registered with data admin site.")

        if url_root == "/admin/uploader/" and not staffuser.is_superuser:
            pytest.skip("Admin site restricted to superuser.")

        c = Client()
        model_name = model.__name__.lower()
        if with_perm:
            add_model_perms(staffuser, model=model_name, action="view")
        c.force_login(staffuser)
        response = c.get(f"{url_root}{model_name}/", follow=False)
        assert response.status_code == (200 if with_perm else 403)

    @pytest.mark.parametrize("with_perm", (True, False))
    @pytest.mark.parametrize("url_root", ("/data/uploader/", "/admin/uploader/"))
    @pytest.mark.parametrize("model", uploader_models)
    def test_admin_add_perms_pages(self, with_perm, staffuser, url_root, model):
        if url_root == "/data/uploader/" and model in SKIP_MODELS:
            pytest.skip("Model not registered with data admin site.")

        if url_root == "/admin/uploader/" and not staffuser.is_superuser:
            pytest.skip("Admin site restricted to superuser.")

        c = Client()
        model_name = model.__name__.lower()
        if with_perm:
            add_model_perms(staffuser, model=model_name, action="add")
        c.force_login(staffuser)
        response = c.get(f"{url_root}{model_name}/add/", follow=False)
        assert response.status_code == (200 if with_perm else 403)

    @pytest.mark.parametrize("with_perm", (True, False))
    @pytest.mark.parametrize("model", uploader_models)
    def test_admin_change_perms_pages(self, with_perm, staffuser, model, mock_data, qcannotators):
        if model in SKIP_MODELS:
            pytest.skip("Model edits restricted to superuser")

        if model in (uploader.models.QCAnnotation, uploader.models.UploadedFile):
            pytest.skip("This data doesn't exist in mock_data fixture.")
        c = Client()
        model_name = model.__name__.lower()
        if with_perm:
            add_model_perms(staffuser, model=model_name, action="change")
        c.force_login(staffuser)

        for obj in model.objects.all():
            url = f"/data/uploader/{model_name}/{obj.pk}/change/"
            response = c.get(url, follow=with_perm)
            expected_resp_code = 200 if with_perm else 403
            assert response.status_code == expected_resp_code

    @pytest.mark.parametrize("with_perm", (True, False))
    @pytest.mark.parametrize("model", uploader_models)
    def test_admin_delete_perms_pages(self, with_perm, staffuser, model, mock_data, qcannotators):
        if model in SKIP_MODELS:
            pytest.skip("Model edits restricted to superuser")

        if model in (uploader.models.QCAnnotation, uploader.models.UploadedFile):
            pytest.skip("This data doesn't exist in mock_data fixture.")
        c = Client()
        model_name = model.__name__.lower()
        if with_perm:
            add_model_perms(staffuser, model=model_name, action="delete")
        c.force_login(staffuser)

        for obj in model.objects.all():
            url = f"/data/uploader/{model_name}/{obj.pk}/delete/"
            response = c.get(url, follow=with_perm)
            expected_resp_code = 200 if with_perm else 403
            assert response.status_code == expected_resp_code
