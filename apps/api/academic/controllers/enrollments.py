from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from ..decorators import controller, get, patch, post, scoped_permission, validate_payload
from ..models import CourseOffering
from ..serializers import (
    EnrollmentSerializer,
    EnrollmentStatusUpdateSerializer,
    RosterImportApplySerializer,
    RosterImportPreviewSerializer,
)
from ..services import (
    EnrollmentService,
    RosterImportConflict,
    RosterImportService,
    academic_service_provider,
)
from .base import AcademicPagination


@controller("enrollments", basename="enrollment")
class EnrollmentController(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Controller for enrollments with constructor injection and guard protection."""

    serializer_class = EnrollmentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = AcademicPagination

    def __init__(
        self,
        service: EnrollmentService | None = None,
        import_service: RosterImportService | None = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.service = service or academic_service_provider.provide(EnrollmentService)
        self.import_service = import_service or academic_service_provider.provide(
            RosterImportService
        )

    def get_queryset(self):
        filters = dict(self.request.query_params.items())
        return self.service.get_queryset(actor=self.request.user, **filters)

    @get()
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @get("{id}")
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @post(
        permission_classes=[
            IsAuthenticated,
            scoped_permission("offering.manage", scope_field="offering"),
        ]
    )
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @patch(
        "{id}",
        permission_classes=[
            IsAuthenticated,
            scoped_permission("grades.edit", scope_field="offering"),
        ],
    )
    @validate_payload(EnrollmentStatusUpdateSerializer)
    def partial_update(self, request, *args, payload=None, **kwargs):
        enrollment = self.get_object()
        updated = self.service.update_status(
            enrollment=enrollment,
            status=payload["status"],
            reason=payload.get("reason", ""),
            actor=request.user,
        )
        return Response(self.get_serializer(updated).data)

    @get(
        "import/template",
        url_name="import-template",
        permission_classes=[
            IsAuthenticated,
            scoped_permission("offering.manage", scope_field="offering"),
        ],
    )
    def import_template(self, request, *args, **kwargs):
        offering = get_object_or_404(CourseOffering, pk=request.query_params.get("offering"))
        return Response(self.import_service.template_payload(offering=offering))

    @post(
        "import/preview",
        url_name="import-preview",
        permission_classes=[
            IsAuthenticated,
            scoped_permission("offering.manage", scope_field="offering"),
        ],
    )
    @validate_payload(RosterImportPreviewSerializer)
    def import_preview(self, request, *args, payload=None, **kwargs):
        return Response(self.import_service.preview(**payload))

    @post(
        "import/apply",
        url_name="import-apply",
        permission_classes=[
            IsAuthenticated,
            scoped_permission("offering.manage", scope_field="offering"),
        ],
    )
    @validate_payload(RosterImportApplySerializer)
    def import_apply(self, request, *args, payload=None, **kwargs):
        try:
            result = self.import_service.apply(actor=request.user, **payload)
        except RosterImportConflict as exc:
            return Response(
                {"code": exc.code, "detail": exc.detail}, status=status.HTTP_409_CONFLICT
            )
        return Response(result, status=status.HTTP_201_CREATED)

    def perform_create(self, serializer):
        serializer.instance = self.service.create(
            actor=self.request.user,
            **serializer.validated_data,
        )

    def perform_update(self, serializer):
        serializer.instance = self.service.update(
            instance=serializer.instance,
            **serializer.validated_data,
        )

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response
