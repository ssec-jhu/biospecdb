from django.contrib import admin
from django.db.models import Q
import django.forms as forms

from .models import BioSample, Observable, Instrument, Patient, SpectralData, Symptom, UploadedFile, Visit, QCAnnotator,\
    QCAnnotation, Center, get_center, BioSampleType


class RestrictedByCenterAdmin(admin.ModelAdmin):
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

    def has_add_permission(self, request):
        return super().has_add_permission(request)

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
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


admin.site.register(BioSampleType)


@admin.register(Instrument)
class InstrumentAdmin(RestrictedByCenterAdmin):
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    list_display = ["spectrometer", "atr_crystal"]
    ordering = ["spectrometer"]


@admin.register(UploadedFile)
class UploadedFileAdmin(RestrictedByCenterAdmin):
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


class QCAnnotationInline(admin.TabularInline):
    model = QCAnnotation
    extra = 1
    show_change_link = True


@admin.register(QCAnnotation)
class QCAnnotationAdmin(RestrictedByCenterAdmin):
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
class QCAnnotatorAdmin(RestrictedByCenterAdmin):
    search_fields = ["name"]
    search_help_text = "Name"
    # TODO: Might need specific user group for timestamps.)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)
    list_display = ["name", "fully_qualified_class_name", "default", "value_type"]


@admin.register(Observable)
class DiseaseAdmin(RestrictedByCenterAdmin):
    search_fields = ["name"]
    search_help_text = "Disease name"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    ordering = ["name"]
    list_filter = ("center", "value_class")
    list_display = ["name", "description", "symptom_count"]

    @admin.display
    def symptom_count(self, obj):
        return len(obj.symptom.all())

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(Q(center=Center.objects.get(pk=request.user.center.pk)) | Q(center=None))


@admin.register(Symptom)
class SymptomAdmin(RestrictedByCenterAdmin):
    search_fields = ["disease__name", "visit__patient__patient_id", "visit__patient__patient_cid"]
    search_help_text = "Disease, Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)
    list_filter = ("visit__patient__center", "visit__patient__gender", "disease")
    list_display = ["patient_id", "disease_name", "days_symptomatic", "severity", "visit"]
    list_editable = ["days_symptomatic", "severity"]

    @admin.display
    def patient_id(self, obj):
        return obj.visit.patient.patient_id

    @admin.display
    def disease_name(self, obj):
        return obj.disease.name

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """ Limit center form fields to user's center, and set initial value as such.
            Exceptions are made for superusers.
        """
        if db_field.name == "disease" and request.user.center:
            center = Center.objects.get(pk=request.user.center.pk)
            kwargs["queryset"] = Disease.objects.filter(Q(center=center) | Q(center=None))
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(visit__patient__center=Center.objects.get(pk=request.user.center.pk))


class SymptomInline(admin.TabularInline):
    model = Symptom
    extra = 10
    show_change_link = True


class SpectralDataInline(admin.StackedInline):
    model = SpectralData
    extra = 1
    radio_fields = {"instrument": admin.HORIZONTAL}
    show_change_link = True


@admin.register(SpectralData)
class SpectralDataAdmin(RestrictedByCenterAdmin):
    radio_fields = {"instrument": admin.HORIZONTAL}

    search_fields = ["bio_sample__visit__patient__patient_id", "bio_sample__visit__patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    list_display = ["patient_id", "instrument", "data"]
    inlines = [QCAnnotationInline]
    ordering = ("-updated_at",)
    list_filter = ("bio_sample__visit__patient__center",
                   "instrument",
                   "spectra_measurement",
                   "bio_sample__sample_type",
                   "bio_sample__sample_processing",
                   "bio_sample__visit__patient__gender")

    @admin.display
    def patient_id(self, obj):
        return obj.bio_sample.visit.patient_id

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(bio_sample__visit__patient__center=Center.objects.get(pk=request.user.center.pk))


class BioSampleInline(admin.TabularInline):
    model = BioSample
    extra = 1
    show_change_link = True


@admin.register(BioSample)
class BioSampleAdmin(RestrictedByCenterAdmin):
    search_fields = ["visit__patient__patient_id", "visit__patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)
    list_filter = ("visit__patient__center", "sample_type", "sample_processing")
    list_display = ["patient_id", "sample_type"]
    inlines = [SpectralDataInline]

    @admin.display
    def patient_id(self, obj):
        return obj.visit.patient_id

    def get_queryset(self, request):
        """ List only objects belonging to user's center. """
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(visit__patient__center=Center.objects.get(pk=request.user.center.pk))


class VisitAdminForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.patient_id:
            self.fields["previous_visit"].queryset = Visit.objects.filter(patient=self.instance.patient_id)


@admin.register(Visit)
class VisitAdmin(RestrictedByCenterAdmin):
    form = VisitAdminForm
    search_fields = ["patient__patient_id", "patient__patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)
    list_filter = ("patient__center",)

    # autocomplete_fields = ["previous_visit"]  # Conflicts with VisitAdminForm queryset.
    inlines = [BioSampleInline, SymptomInline]

    list_display = ["patient_id", "visit_count", "gender", "previous_visit"]

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


class VisitInline(admin.TabularInline):
    form = VisitAdminForm
    model = Visit
    extra = 1
    show_change_link = True


@admin.register(Patient)
class PatientAdmin(RestrictedByCenterAdmin):
    inlines = [VisitInline]
    search_fields = ["patient_id", "patient_cid"]
    search_help_text = "Patient ID or CID"
    readonly_fields = ["created_at", "updated_at"]  # TODO: Might need specific user group.
    date_hierarchy = "updated_at"
    ordering = ("-updated_at",)
    list_filter = ("center", "gender")

    list_display = ["patient_id", "patient_cid", "gender", "age", "visit_count", "center"]

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
data_admin.register(Symptom, admin_class=SymptomAdmin)
data_admin.register(BioSample, admin_class=BioSampleAdmin)
data_admin.register(SpectralData, admin_class=SpectralDataAdmin)
data_admin.register(UploadedFile, admin_class=UploadedFileAdmin)
data_admin.register(Instrument, admin_class=InstrumentAdmin)
data_admin.register(QCAnnotation, admin_class=QCAnnotationAdmin)
data_admin.register(QCAnnotator, admin_class=QCAnnotatorAdmin)
data_admin.register(Disease, admin_class=DiseaseAdmin)
