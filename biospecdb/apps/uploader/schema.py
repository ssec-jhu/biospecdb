import graphene
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

import uploader.models


class CenterNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Center
        filter_fields = {"id": ["exact"],
                         "name": ["exact", "icontains", "istartswith"],
                         "country": ["exact", "icontains", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class PatientNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Patient
        filter_fields = {"patient_id": ["exact"],
                         "patient_cid": ["exact"],
                         "gender": ["exact", "icontains", "istartswith"],
                         "center": ["exact"]}
        interfaces = (graphene.relay.Node,)


class VisitNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Visit
        filter_fields = {"patient": ["exact"],
                         "patient_age": ["exact"],
                         "previous_visit": ["exact"]}
        interfaces = (graphene.relay.Node,)


class ObservableNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Observable
        filter_fields = {"category": ["exact", "icontains", "istartswith"],
                         "name": ["exact", "icontains", "istartswith"],
                         "description": ["exact", "icontains", "istartswith"],
                         "alias": ["exact", "icontains", "istartswith"],
                         "center": ["exact"],
                         "value_class": ["exact", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class ObservationNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Observation
        filter_fields = {"visit": ["exact"],
                         "observable": ["exact"],
                         "days_observed": ["exact"],
                         "severity": ["exact"],
                         "observable_value": ["exact"]}
        interfaces = (graphene.relay.Node,)


class InstrumentNode(DjangoObjectType):
    class Meta:
        model = uploader.models.Instrument
        filter_fields = {"spectrometer": ["exact", "icontains", "istartswith"],
                         "atr_crystal": ["exact", "icontains", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class BioSampleTypeNode(DjangoObjectType):
    class Meta:
        model = uploader.models.BioSampleType
        filter_fields = {"name": ["exact", "icontains", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class BioSampleNode(DjangoObjectType):
    class Meta:
        model = uploader.models.BioSample
        filter_fields = {"visit": ["exact"],
                         "sample_type": ["exact"],
                         "sample_processing": ["exact", "icontains", "istartswith"],
                         "freezing_temp": ["exact"],
                         "thawing_time": ["exact"]}
        interfaces = (graphene.relay.Node,)


class SpectraMeasurementTypeNode(DjangoObjectType):
    class Meta:
        model = uploader.models.SpectraMeasurementType
        filter_fields = {"name": ["exact", "icontains", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class SpectralDataNode(DjangoObjectType):
    class Meta:
        model = uploader.models.SpectralData
        filter_fields = {"id": ["exact"],
                         "instrument": ["exact"],
                         "bio_sample": ["exact"],
                         "spectra_measurement": ["exact"],
                         "acquisition_time": ["exact"],
                         "n_coadditions": ["exact"],
                         "resolution": ["exact"]}
                         # "data")
        interfaces = (graphene.relay.Node,)


class QCAnnotatorNode(DjangoObjectType):
    class Meta:
        model = uploader.models.QCAnnotator
        filter_fields = {"name": ["exact", "icontains", "istartswith"],
                         "fully_qualified_class_name": ["exact", "icontains", "istartswith"],
                         "value_type": ["exact", "icontains", "istartswith"],
                         "description": ["exact", "icontains", "istartswith"],
                         "default": ["exact", "icontains", "istartswith"]}
        interfaces = (graphene.relay.Node,)


class QCAnnotationNode(DjangoObjectType):
    class Meta:
        model = uploader.models.QCAnnotation
        filter_fields = {"value": ["exact"],
                         "annotator": ["exact"],
                         "spectral_data": ["exact"]}
        interfaces = (graphene.relay.Node,)


class Query(graphene.ObjectType):
    patient = graphene.relay.Node.Field(PatientNode)
    all_patients = DjangoFilterConnectionField(PatientNode)

    visit = graphene.relay.Node.Field(VisitNode)
    all_visits = DjangoFilterConnectionField(VisitNode)

    observable = graphene.relay.Node.Field(ObservableNode)
    all_observables = DjangoFilterConnectionField(ObservableNode)

    observation = graphene.relay.Node.Field(ObservationNode)
    all_observations = DjangoFilterConnectionField(ObservationNode)

    instrument = graphene.relay.Node.Field(InstrumentNode)
    all_instruments = DjangoFilterConnectionField(InstrumentNode)

    bio_sample_type = graphene.relay.Node.Field(BioSampleTypeNode)
    all_bio_sample_types = DjangoFilterConnectionField(BioSampleTypeNode)

    bio_sample = graphene.relay.Node.Field(BioSampleNode)
    all_bio_samples = DjangoFilterConnectionField(BioSampleNode)

    spectra_measurement_type = graphene.relay.Node.Field(SpectraMeasurementTypeNode)
    all_spectra_measurement_types = DjangoFilterConnectionField(SpectraMeasurementTypeNode)

    spectral_data = graphene.relay.Node.Field(SpectralDataNode)
    all_spectral_data = DjangoFilterConnectionField(SpectralDataNode)

    qc_annotator = graphene.relay.Node.Field(QCAnnotatorNode)
    all_qc_annotators = DjangoFilterConnectionField(QCAnnotatorNode)

    qc_annotation = graphene.relay.Node.Field(QCAnnotationNode)
    all_qc_annotations = DjangoFilterConnectionField(QCAnnotationNode)


class Mutation(graphene.ObjectType):
    ...


schema = graphene.Schema(query=Query)
