"""biospecdb URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from graphene_django.views import GraphQLView

from uploader import views
from uploader.admin import data_admin

admin.site.site_header = "Biosample Spectral Repository administration"

urlpatterns = [
    path('', RedirectView.as_view(pattern_name="home", permanent=True)),
    path('uploader/', include('biospecdb.apps.uploader.urls')),
    path('admin/', admin.site.urls),
    path('home/', views.home, name='home'),
    path('display/', views.display_xlsx, name='MetadataDisplay'),
    path('explorer/', include('explorer.urls')),
    path('data/', data_admin.urls),
    path("graphql", GraphQLView.as_view(graphiql=True)),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
