from django.urls import path
from django.conf import settings
from django.conf.urls.static import static
from . import views

app_name = 'uploader'

urlpatterns = [
    path('data_input/', views.data_input, name='DataInputForm'),
    path('data_search/', views.data_search, name='DataSearchForm')
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
