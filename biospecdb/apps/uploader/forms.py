import pandas as pd
from django import forms
from django.db import models

from biospecdb.util import to_uuid
from uploader.io import read_spectral_data_table, get_file_info
from uploader.models import UploadedFile, Patient, SpectralData, Instrument, BioSample, Symptom, Disease, Visit
from .loaddata import save_data_to_db, update_db


class FileUploadForm(forms.ModelForm):
    class Meta:
        model = UploadedFile
        fields = ["meta_data_file", "spectral_data_file"]


def map_model_fields_to_form_field(field, inc_choices=False, **kwargs):
    # TODO: The following mapping may not be functionally complete.
    field_obj = field.field
    opts = dict(required=not field_obj.blank,
                label=field_obj.verbose_name,
                validators=field_obj.validators,
                help_text=field_obj.help_text)

    if inc_choices:
        opts["choices"] = field_obj.choices

    initial = field_obj.default
    opts["initial"] = None if initial is models.NOT_PROVIDED else initial

    if kwargs:
        opts.update(kwargs)

    return opts


class DataInputForm(forms.Form):
        
    patient_id = forms.UUIDField(**map_model_fields_to_form_field(Patient.patient_id))
    gender = forms.ChoiceField(**map_model_fields_to_form_field(Patient.gender, inc_choices=True))
    days_symptomatic = forms.IntegerField(**map_model_fields_to_form_field(Symptom.days_symptomatic))
    patient_age = forms.IntegerField(**map_model_fields_to_form_field(Visit.patient_age))
    spectra_measurement = forms.ChoiceField(**map_model_fields_to_form_field(SpectralData.spectra_measurement,
                                                                             inc_choices=True))

    instrument = forms.ModelChoiceField(required=(not Instrument.spectrometer.field.blank or
                                                  not Instrument.atr_crystal.field.blank),
                                        label="Instrument",
                                        help_text="Instrument used to measure spectral data",
                                        queryset=Instrument.objects.all())

    acquisition_time = forms.IntegerField(**map_model_fields_to_form_field(SpectralData.acquisition_time))
    n_coadditions = forms.IntegerField(**map_model_fields_to_form_field(SpectralData.n_coadditions))
    resolution = forms.IntegerField(**map_model_fields_to_form_field(SpectralData.resolution))
    sample_type = forms.ChoiceField(**map_model_fields_to_form_field(BioSample.sample_type, inc_choices=True))
    sample_processing = forms.CharField(**map_model_fields_to_form_field(BioSample.sample_processing))
    freezing_temp = forms.FloatField(**map_model_fields_to_form_field(BioSample.freezing_temp))
    thawing_time = forms.IntegerField(**map_model_fields_to_form_field(BioSample.thawing_time))
    spectral_data = forms.FileField(**map_model_fields_to_form_field(SpectralData.data))
    
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop("request")
        super().__init__(*args, **kwargs)

        for disease in Disease.objects.all():  # Dynamically add disease fields from the Disease table
            if (field_type := disease.value_class) == "FLOAT":
                field_type = forms.FloatField(required=not Symptom.disease_value.field.blank,
                                              initial=Symptom.disease_value.field.default,
                                              label=disease.alias)
            elif field_type == "STR":
                field_type = forms.CharField(required=not Symptom.disease_value.field.blank,
                                             initial=Symptom.disease_value.field.default,
                                             label=disease.alias)
            elif field_type == "BOOL":
                # TODO: Reconsider use of NullBooleanField and NullBooleanSelect.
                field_type = forms.NullBooleanField(required=not Symptom.disease_value.field.blank,
                                                    label=disease.alias,
                                                    initial=Symptom.disease_value.field.default,
                                                    widget=forms.NullBooleanSelect)  # TODO: Reconsider widget use.
            self.fields[disease.name] = field_type

    def to_df(self):
        # Create a dictionary from the cleaned form data
        data = {}
        for key, value in self.cleaned_data.items():
            label = self.fields[key].label
            if label:
                data[label] = value
            else:
                data[key] = value

        # Special case instrument.
        instrument = data.pop("Instrument")
        data[Instrument.spectrometer.field.verbose_name] = instrument.spectrometer
        data[Instrument.atr_crystal.field.verbose_name] = instrument.atr_crystal

        data.pop("Spectral data file")  # This is not a part of meta data, so should be removed.
        df = pd.DataFrame(data, index=[to_uuid(data[self.fields["patient_id"].label])])
        canonic_data = df.rename(columns=lambda x: x.lower())
        return canonic_data

    def massage_data(self):
        # WARNING!: This func is not responsible for validation and self.is_valid() must be called first.

        # Read in all data
        meta_data = self.to_df()
        spec_data = read_spectral_data_table(*get_file_info(self.cleaned_data["spectral_data"]))

        # This uses a join so returns the joined data so that it doesn't go to waste if needed, which it is here.
        return UploadedFile.join_with_validation(meta_data, spec_data)

    def clean(self):
        super().clean()

        # Fail early.
        if self.errors:
            return

        # Dry-run save to run complex model validation without actually saving to DB.
        massaged_data = self.massage_data()
        self._cleaned_model_objects = save_data_to_db(None,
                                                      None,
                                                      center=self.request.user.center,
                                                      joined_data=massaged_data,
                                                      dry_run=True)

    def save(self):
        # WARNING!: This func is NOT responsible for validation and self.is_valid() must be called first!

        # Ingest into DB.
        save_data_to_db(None, None, center=self.request.user.center, joined_data=self.massage_data())    

    def update(self):
        # WARNING!: This func is NOT responsible for validation and self.is_valid() must be called first!

        # Update DB.
        update_db(None, None, center=self.request.user.center, joined_data=self.massage_data())
