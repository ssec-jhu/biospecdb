from django.apps import AppConfig


class UploaderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'uploader'
    verbose_name = "Biosample Spectral Repository"

    def ready(self):
        import explorer.charts
        import explorer.views.utils
        from uploader.charts.charts import get_line_chart, get_pie_chart
        from uploader.charts.utils import query_viewmodel

        # Monkeypatch explorer charts.
        explorer.charts.get_pie_chart = get_pie_chart
        explorer.charts.get_line_chart = get_line_chart
        explorer.views.utils.query_viewmodel = query_viewmodel

