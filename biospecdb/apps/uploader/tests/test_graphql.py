import json

from django.test import Client
import pytest
from graphene_django.utils.testing import graphql_query

from uploader.tests.conftest import add_model_perms, app_models
from uploader.models import UploadedFile

uploader_models = app_models()
SKIP_MODELS = [UploadedFile]


@pytest.mark.django_db(databases=["default", "bsr"])
@pytest.mark.parametrize("model", uploader_models)
class TestGrapQL:
    @pytest.mark.parametrize("user", ("non_staffuser", "staffuser", "superuser"))
    def test_authentication(self, request, user, model, mock_data):
        if model in SKIP_MODELS:
            pytest.skip("Model has no graphql function")

        client = Client()
        user = request.getfixturevalue(user)
        client.force_login(user)

        query = f"""{{
              all{model.__name__}s {{
                edges {{
                  node {{
                    id
                  }}
                }}
              }}
            }}
            """
        response = graphql_query(query, client=client)
        if user.is_staff or user.is_superuser:
            assert response.status_code == 200
            content = json.loads(response.content)
            assert 'errors' not in content
        else:
            assert response.status_code == 302

    @pytest.mark.parametrize("with_perm", (True, False))
    def test_query_view_permission(self, with_perm, staffuser, model, mock_data):
        if model in SKIP_MODELS:
            pytest.skip("Model has no graphql function")

        client = Client()
        model_name = model.__name__.lower()
        if with_perm:
            add_model_perms(staffuser, model=model_name, action="view")
        client.force_login(staffuser)

        query = f"""{{
                 all{model.__name__}s {{
                   edges {{
                     node {{
                       id
                     }}
                   }}
                 }}
               }}
               """
        response = graphql_query(query, client=client)

        if with_perm:
            assert response.status_code == 200
            content = json.loads(response.content)
            assert 'errors' not in content
        else:
            assert response.status_code == 400
