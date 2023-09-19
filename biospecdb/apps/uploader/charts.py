from io import StringIO
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from django.conf import settings
from biospecdb.util import read_individual_spectral_data
from uploader.models import Disease, Patient, SpectralData


def fig_to_html(fig) -> str:
    buffer = StringIO()
    fig.write_html(buffer, auto_open=False, full_html=False)
    buffer.seek(0)
    graph = buffer.getvalue()
    buffer.close()
    return graph


def count_bool_diseases(result: "QueryResult"):  # noqa: F821
    if len(result.data) < 1:
        return

    bool_diseases = [d.name for d in Disease.objects.all() if d.value_class == "BOOL"]
    df = pd.DataFrame(result.data, columns=result.header_strings)
    df = df[bool_diseases].replace({"True": True, "False": False})
    return df.sum()


def get_pie_chart(result: "QueryResult") -> Optional[str]:  # noqa: F821
    try:
        counts = count_bool_diseases(result)

        if counts is None:
            return

        fig = px.pie(counts, values=counts.values, names=counts.index, title=f"SQL query: '{result.sql}'")
        return fig_to_html(fig)
    except Exception:
        if settings.DEBUG:
            raise
        else:
            return


def get_line_chart(result: "QueryResult") -> Optional[str]:  # noqa: F821
    if len(result.data) < 1:
        return

    try:
        df = pd.DataFrame(result.data, columns=result.header_strings)
        df = df[[Patient.patient_id.field.name, SpectralData.data.field.name]]

        fig = go.Figure()
        fig.update_layout(xaxis_title="Wavelength",
                          yaxis_title="Intensity",
                          title=f"Spectral Data for SQL query: '{result.sql}'")
        for _, (patient_id, filename) in df.iterrows():
            spectral_data, _patient_id = read_individual_spectral_data(filename)
            fig.add_scatter(x=spectral_data["wavelength"],
                            y=spectral_data["intensity"],
                            name=patient_id)

        return fig_to_html(fig)
    except Exception:
        if settings.DEBUG:
            raise
        else:
            return
