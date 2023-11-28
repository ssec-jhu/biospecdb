from django.contrib.auth import get_user_model
from django.test import Client
import pytest

from uploader.tests.conftest import add_model_perms, app_models
import uploader.models


User = get_user_model()

SKIP_MODELS = [uploader.models.BioSampleType, uploader.models.SpectraMeasurementType]


uploader_models = app_models()


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
