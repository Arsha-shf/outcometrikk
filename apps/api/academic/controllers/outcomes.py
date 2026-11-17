from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import action
from rest_framework.response import Response

from ..serializers import (
    ProgramOutcomeSerializer,
    ProgramOutcomeSetActivateSerializer,
    ProgramOutcomeSetSerializer,
)
from ..services import ProgramOutcomeService, ProgramOutcomeSetService
from .base import AcademicController


class ProgramOutcomeSetController(AcademicController):
    serializer_class = ProgramOutcomeSetSerializer
    service_class = ProgramOutcomeSetService
    filter_fields = ("program", "status", "version")

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        instance = self.get_object()
        payload = ProgramOutcomeSetActivateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        try:
            instance = self.get_service().activate(instance=instance, **payload.validated_data)
        except DjangoValidationError as exc:
            self.raise_validation_error(exc)
        return Response(self.get_serializer(instance).data)


class ProgramOutcomeController(AcademicController):
    serializer_class = ProgramOutcomeSerializer
    service_class = ProgramOutcomeService
    filter_fields = ("outcome_set", "code")
