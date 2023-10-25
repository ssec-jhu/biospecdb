from inspect import signature

from django.contrib import admin
from django.db.models import Q
from django.db.utils import OperationalError
import django.forms as forms
from nested_inline.admin import NestedStackedInline, NestedTabularInline, NestedModelAdmin

from .models import BioSample, Observable, Instrument, Patient, SpectralData, Observation, UploadedFile, Visit,\
    QCAnnotator, QCAnnotation, Center, get_center, BioSampleType, SpectraMeasurementType


class RestrictedByCenterMixin:
    """ Restrict admin access to objects belong to user's center. """
    def _has_perm(self, request, obj):
        user_center = request.user.center if request.user else None

        if (not user_center) or (obj is None):
            # Those without centers "own" all.
            return True  # security risk!?

        obj_center = get_center(obj)
        if not obj_center:
            # Objects without centers are "owned" by all.
            return True

        return obj_center == user_center

    def has_view_permission(self, request, obj=None):
        has_base_perm = super().has_view_permission(request, obj=obj)

        if obj is None or request.user.is_superuser:
            return has_base_perm

        return has_base_perm and self._has_perm(request, obj)

    def has_module_permission(self, request):
        return super().has_module_permission(request)

    def has_add_permission(self, request, obj=None):
        # Note: The signature isn't symmetric for ``admin.ModelAdmin`` and ``admin.InlineModelAdmin`` so we introspect
        # their func signatures. Their signatures are:
        # * ``admin.ModelAdmin.has_add_permission(self, request)``
        # * ``admin.InlineModelAdmin.has_add_permission(self, request, obj=None)``
        kwargs = {"obj": obj} if "obj" in signature(super().has_add_permission).parameters else {}
        return super().has_add_permission(request, **kwargs)

    def has_change_permission(self, request, obj=None):
        has_base_perm = super().has_change_permission(request, obj=obj)

        if obj is None or request.user.is_superuser:
            return has_base_perm

        return has_base_perm and self._has_perm(request, obj)

    def has_delete_permission(self, request, obj=None):
        has_base_perm = super().has_delete_permission(request, obj)

        if obj is None or request.user.is_superuser:
            return has_base_perm

        return has_base_perm and self._has_perm(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """ Limit center form fields to user's center, and set initial value as such.
            Exceptions are made for superusers.
        """
        if db_field.name == "center" and request.user.center:
            kwargs["initial"] = Center.objects.get(pk=request.user.center.pk)
            if not request.user.is_superuser:
                kwargs["queryset"] = Center.objects.filter(pk=request.user.center.pk)
        elif db_field.name == "observable" and request.user.center:
            center = Center.objects.get(pk=request.user.center.pk)
            kwargs["queryset"] = Observable.objects.filter(Q(center=center) | Q(center=None))

        return super().formfield_for_foreignkey(db_field, request, **kwargs)


admin.site.register(BioSampleType)
admin.site.register(SpectraMeasurementType)


@admin.register(Instrument)
class InstrumentAdmin(RestrictedByCenterMixin, admin.ModelAdmin):
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    list_display = ["spectrometer", "atr_crystal"]
    ordering = ["spectrometer"]


@admin.register(UploadedFile)
class UploadedFileAdmin(RestrictedByCenterMixin, admin.ModelAdmin):
    search_fields = ["created_at"]
    search_help_text = "Creation timestamp"
    list_display = ["pk", "created_at", "meta_data_file", "spectral_data_file", "center"]
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "created_at"
    ordering = ("-updated_at",)
    list_filter = ("center",)

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(center=Center.objects.get(pk=request.user.center.pk))


class QCAnnotationInline(RestrictedByCenterMixin, NestedTabularInline):
    model = QCAnnotation
    extra = 0
    min_num = 1
    show_change_link = True


@admin.register(QCAnnotation)
class QCAnnotationAdmin(RestrictedByCenterMixin, admin.ModelAdmin):
    search_fields = ["annotator__name",
                     "spectral_data__bio_sample__visit__patient__patient_id",
                     "spectral_data__bio_sample__visit__patient__patient_cid"]
    search_help_text = "Annotator Name, Patient ID or CID"
    readonly_fields = ("value", "created_at", "updated_at")  # TODO: Might need specific user group for timestamps.
    list_display = ["annotator_name", "value", "annotator_value_type", "updated_at"]
    ordering = ("-updated_at",)
    list_filter = ("spectral_data__bio_sample__visit__patient__center", "annotator__name")

    @admin.display
    def annotator_name(self, obj):
        return obj.annotator.name

    @admin.display
    def annotator_value_type(self, obj):
        return obj.annotator.value_type

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        center = Center.objects.get(pk=request.user.center.pk)
        return qs.filter(spectral_data__bio_sample__visit__patient__center=center)


@admin.register(QCAnnotator)
class QCAnnotatorAdmin(RestrictedByCenterMixin, admin.ModelAdmin):
    search_fields = ["name"]
    search_help_text = "Name"
    # TODO: Might need specific user group for timestamps.)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)
    list_display = ["name", "fully_qualified_class_name", "default", "value_type"]


@admin.register(Observable)
class ObservableAdmin(RestrictedByCenterMixin, NestedModelAdmin):
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    ordering = ["name"]
    search_fields = ["name"]
    search_help_text = "Observable name"
    list_filter = ("center", "category", "value_class")
    list_display = ["category", "name", "description", "observation_count"]

    @admin.display
    def observation_count(self, obj):
        return len(obj.observation.all())

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(Q(center=Center.objects.get(pk=request.user.center.pk)) | Q(center=None))


class ObservationMixin:
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    ordering = ("-updated_at",)

    @admin.display
    def patient_id(self, obj):
        return obj.visit.patient.patient_id

    @admin.display
    def observable_name(self, obj):
        return obj.observable.name

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(visit__patient__center=Center.objects.get(pk=request.user.center.pk))


class ObservationInlineForm(forms.ModelForm):
    observables = iter([])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            self.fields["observable"].initial = next(self.observables)
        except StopIteration:
            pass


class ObservationInline(ObservationMixin, RestrictedByCenterMixin, NestedTabularInline):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            kwargs = {"observables": iter(Observable.objects.all())}
        except OperationalError:
            kwargs = {}

        self.form = type("NewObservationForm", (ObservationInlineForm,), kwargs)

    extra = 0
    model = Observation
    fk_name = "visit"
    show_change_link = True

    def get_min_num(self, request, obj=None, **kwargs):
        if obj and obj.pk:
            min_num = len(obj.observation.all())
        else:
            # Note: Calling ``len(self.formfield_for_foreignkey(db_field, request)`` would be better, however, it's not
            # clear how to correctly pass ``db_field``. The following was copied from
            # ``RestrictedByCenterMixin.formfield_for_foreignkey``.
            center = Center.objects.get(pk=request.user.center.pk)
            min_num = len(Observable.objects.filter(Q(center=center) | Q(center=None)))

        return min_num


@admin.register(Observation)
class ObservationAdmin(ObservationMixin, RestrictedByCenterMixin, NestedModelAdmin):
    search_fields = ["observable__name", "visit__patient__patient_id", "visit__patient__patient_cid"]
    search_help_text = "Observable, Patient ID or CID"
    date_hierarchy = "updated_at"
    list_filter = ("visit__patient__center", "observable__category", "visit__patient__gender", "observable")
    list_display = ["patient_id", "observable_name", "days_observed", "severity", "visit"]
    list_editable = ["days_observed", "severity"]


class SpectralDataForm(forms.ModelForm):
    def is_multipart(self):
        return True


class SpectralDataMixin:
    form = SpectralDataForm
    radio_fields = {"instrument": admin.HORIZONTAL}
    ordering = ("-updated_at",)

    @admin.display
    def patient_id(self, obj):
        return obj.bio_sample.visit.patient_id

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(bio_sample__visit__patient__center=Center.objects.get(pk=request.user.center.pk))


@admin.register(SpectralData)
class SpectralDataAdmin(SpectralDataMixin, RestrictedByCenterMixin, NestedModelAdmin):
    search_fields = ["bio_sample__visit__patient__patient_id", "bio_sample__visit__patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    list_display = ["patient_id", "instrument", "data"]
    list_filter = ("bio_sample__visit__patient__center",
                   "instrument",
                   "spectra_measurement",
                   "bio_sample__sample_type",
                   "bio_sample__sample_processing",
                   "bio_sample__visit__patient__gender")
    inlines = [QCAnnotationInline]


class SpectralDataInline(SpectralDataMixin, RestrictedByCenterMixin, NestedStackedInline):
    form = SpectralDataForm
    model = SpectralData
    extra = 0
    min_num = 1
    fk_name = "bio_sample"
    show_change_link = True


class BioSampleMixin:
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    ordering = ("-updated_at",)

    @admin.display
    def patient_id(self, obj):
        return obj.visit.patient_id

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(visit__patient__center=Center.objects.get(pk=request.user.center.pk))


@admin.register(BioSample)
class BioSampleAdmin(BioSampleMixin, RestrictedByCenterMixin, NestedModelAdmin):
    search_fields = ["visit__patient__patient_id", "visit__patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    date_hierarchy = "updated_at"
    list_filter = ("visit__patient__center", "sample_type", "sample_processing")
    list_display = ["patient_id", "sample_type"]
    inlines = [SpectralDataInline]


class BioSampleInline(BioSampleMixin, RestrictedByCenterMixin, NestedStackedInline):
    model = BioSample
    extra = 0
    min_num = 1
    show_change_link = True
    fk_name = "visit"
    inlines = [SpectralDataInline]


class VisitAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.patient_id:
            self.fields["previous_visit"].queryset = Visit.objects.filter(patient=self.instance.patient_id)


class VisitAdminMixin:
    form = VisitAdminForm
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    ordering = ("-updated_at",)

    @admin.display
    def patient_id(self, obj):
        return obj.patient.patient_id

    @admin.display
    def visit_count(self, obj):
        return obj.visit_number

    @admin.display
    def gender(self, obj):
        return obj.patient.gender

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(patient__center=Center.objects.get(pk=request.user.center.pk))


class VisitInline(VisitAdminMixin, RestrictedByCenterMixin, NestedTabularInline):
    model = Visit
    extra = 0
    min_num = 1
    show_change_link = True
    fk_name = "patient"
    inlines = [BioSampleInline, ObservationInline]


@admin.register(Visit)
class VisitAdmin(VisitAdminMixin, RestrictedByCenterMixin, NestedModelAdmin):
    search_fields = ["patient__patient_id", "patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    date_hierarchy = "updated_at"
    list_filter = ("patient__center",)
    # autocomplete_fields = ["previous_visit"]  # Conflicts with VisitAdminForm queryset.
    list_display = ["patient_id", "visit_count", "gender", "previous_visit"]
    inlines = [BioSampleInline, ObservationInline]


@admin.register(Patient)
class PatientAdmin(RestrictedByCenterMixin, NestedModelAdmin):
    search_fields = ["patient_id", "patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)
    list_filter = ("center", "gender")
    list_display = ["patient_id", "patient_cid", "gender", "age", "visit_count", "center"]
    inlines = [VisitInline]

    @admin.display
    def age(self, obj):
        age = 0
        for visit in obj.visit.all():
            age = max(age, visit.patient_age)
        return age

    @admin.display
    def visit_count(self, obj):
        return len(obj.visit.all())

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(center=Center.objects.get(pk=request.user.center.pk))

# NOTE: The following admin can be used to visually sanity check that changes by user.models.Center to the "default" DB
# get reflected in the "bsr" DB. We never want uploader.models.Center to be editable by any admin page, so we restrict
# access below even if this is never used. Admin functionality belong to the admin page for ``user.models.Center``.
# @admin.register(Center)
# class CenterAdmin(admin.ModelAdmin):
#     fields = ("name", "country", "id")
#     list_display = ("name", "country")
#     readonly_fields = ("name", "country", "id")
#
#     def has_view_permission(self, request, obj=None):
#         return request.user.is_superuser
#
#     def has_module_permission(self, request):
#         return request.user.is_superuser
#
#     def has_add_permission(self, request):
#         return False
#
#     def has_change_permission(self, request, obj=None):
#         return False
#
#     def has_delete_permission(self, request, obj=None):
#         return False


class DataAdminSite(admin.AdminSite):
    site_header = "Biosample Spectral Repository"
    index_title = "Data Administration"
    site_title = index_title


data_admin = DataAdminSite(name="data_admin")
data_admin.register(Patient, admin_class=PatientAdmin)
data_admin.register(Visit, admin_class=VisitAdmin)
data_admin.register(Observation, admin_class=ObservationAdmin)
data_admin.register(BioSample, admin_class=BioSampleAdmin)
data_admin.register(SpectralData, admin_class=SpectralDataAdmin)
data_admin.register(UploadedFile, admin_class=UploadedFileAdmin)
data_admin.register(Instrument, admin_class=InstrumentAdmin)
data_admin.register(QCAnnotation, admin_class=QCAnnotationAdmin)
data_admin.register(QCAnnotator, admin_class=QCAnnotatorAdmin)
data_admin.register(Observable, admin_class=ObservableAdmin)
