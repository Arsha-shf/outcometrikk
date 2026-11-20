"""CSV roster preview and atomic import for a course offering (ROST-01)."""

from __future__ import annotations

import csv
import hashlib
import io
from typing import Any

from access.models import AuditEvent, RoleAssignment, Scope
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from wireup import injectable

from ..models import CourseOffering, Enrollment, ProgramMembership
from .enrollments import EnrollmentService
from .grade_import import compute_csv_checksum, sanitize_filename

MAX_ROSTER_BYTES = 1 * 1024 * 1024  # 1 MB UTF-8
MAX_ROSTER_ROWS = 2_000
REQUIRED_COLUMNS = ("student_identifier",)
ALL_COLUMNS = REQUIRED_COLUMNS

# Row error codes that mean "already handled", not "bad data".
DUPLICATE_CODES = frozenset({"duplicate_row", "already_enrolled"})


def _normalize(csv_text: str) -> str:
    return csv_text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")


def compute_roster_fingerprint(offering: CourseOffering) -> str:
    """Hash of the offering's current roster. Any enrollment change alters it."""
    rows = (
        Enrollment.objects.filter(offering=offering)
        .order_by("student_id")
        .values_list("student_id", "status")
    )
    body = "|".join(f"{sid}:{status}" for sid, status in rows)
    return hashlib.sha256(f"{offering.status}|{body}".encode()).hexdigest()


class RosterImportConflict(Exception):
    """Raised when the preview is stale (HTTP 409)."""

    def __init__(self, *, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


@injectable
class RosterImportService:
    """Previews and atomically applies a CSV roster for one offering."""

    def __init__(
        self,
        enrollment_service: EnrollmentService | None = None,
        *,
        actor: Any = None,
    ):
        self.enrollment_service = enrollment_service or EnrollmentService()
        self.actor = actor

    def template_payload(self, *, offering: CourseOffering) -> dict[str, Any]:
        candidate = (
            ProgramMembership.objects.filter(
                program_id=offering.program_id, status=ProgramMembership.Status.ACTIVE
            )
            .exclude(user__academic_enrollments__offering=offering)
            .order_by("student_number")
            .first()
        )
        sample = candidate.student_number if candidate else "S1001"
        return {
            "offering_id": str(offering.pk),
            "columns": list(ALL_COLUMNS),
            "required_columns": list(REQUIRED_COLUMNS),
            "max_bytes": MAX_ROSTER_BYTES,
            "max_rows": MAX_ROSTER_ROWS,
            "sample_csv": f"student_identifier\n{sample}\n",
        }

    def _parse(self, csv_text: str) -> list[dict[str, Any]]:
        if not isinstance(csv_text, str):
            raise ValidationError({"csv_text": "CSV content must be a UTF-8 string."})
        if len(csv_text.encode("utf-8")) > MAX_ROSTER_BYTES:
            raise ValidationError(
                {"csv_text": f"CSV exceeds maximum size of {MAX_ROSTER_BYTES} bytes (1 MB)."}
            )
        normalized = _normalize(csv_text)
        if not normalized.strip():
            raise ValidationError({"csv_text": "CSV content cannot be empty."})

        reader = csv.reader(io.StringIO(normalized))
        headers = [h.strip() for h in next(reader)]
        if len(set(headers)) != len(headers):
            raise ValidationError({"csv_text": "Duplicate CSV header columns."})
        unknown = [h for h in headers if h not in ALL_COLUMNS]
        if unknown:
            raise ValidationError(
                {
                    "csv_text": f"Unknown CSV header columns: {', '.join(unknown)}. "
                    f"Allowed columns: {', '.join(ALL_COLUMNS)}."
                }
            )
        missing = [c for c in REQUIRED_COLUMNS if c not in headers]
        if missing:
            raise ValidationError(
                {"csv_text": f"Missing required CSV columns: {', '.join(missing)}."}
            )

        idx = headers.index("student_identifier")
        parsed: list[dict[str, Any]] = []
        for raw in reader:
            if not any(cell.strip() for cell in raw):
                continue
            if len(parsed) >= MAX_ROSTER_ROWS:
                raise ValidationError(
                    {"csv_text": f"CSV exceeds maximum row limit of {MAX_ROSTER_ROWS} rows."}
                )
            extra = len(raw) > len(headers) and any(c.strip() for c in raw[len(headers) :])
            identifier = raw[idx].strip() if idx < len(raw) else ""
            parsed.append(
                {
                    "row_number": len(parsed) + 1,
                    "identifier": identifier,
                    "extra_columns": extra,
                    "width": len(raw),
                }
            )
        if not parsed:
            raise ValidationError({"csv_text": "CSV must contain at least one data row."})
        return parsed

    def preview(
        self, *, offering: CourseOffering, csv_text: str, filename: str = ""
    ) -> dict[str, Any]:
        """Classify every row as enroll / duplicate / invalid. Writes nothing."""
        if offering.status != CourseOffering.Status.ACTIVE:
            raise ValidationError({"offering": "The offering is not active."})

        parsed = self._parse(csv_text)
        identifiers = {r["identifier"] for r in parsed if r["identifier"]}

        # Scope: only ACTIVE members of THIS offering's program can be resolved.
        memberships = list(
            ProgramMembership.objects.filter(
                program_id=offering.program_id, status=ProgramMembership.Status.ACTIVE
            )
            .filter(Q(student_number__in=identifiers) | Q(user__username__in=identifiers))
            .select_related("user")
        )
        by_number = {m.student_number: m for m in memberships}
        by_username = {m.user.username: m for m in memberships}
        has_student_role = set(
            RoleAssignment.objects.filter(
                scope_id=offering.pk,
                role_id="student",
                revoked_at__isnull=True,
                user_id__in=[m.user_id for m in memberships],
            ).values_list("user_id", flat=True)
        )
        enrolled = set(
            Enrollment.objects.filter(offering=offering).values_list("student_id", flat=True)
        )

        seen: set[Any] = set()
        rows: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        counts = {"enroll": 0, "duplicate": 0, "invalid": 0}

        for r in parsed:
            row_errors: list[dict[str, Any]] = []

            def err(code: str, message: str, _n: int = r["row_number"], _l=row_errors) -> None:
                _l.append(
                    {
                        "row_number": _n,
                        "column": "student_identifier",
                        "code": code,
                        "message": message,
                    }
                )

            ident = r["identifier"]
            member = None
            if r["extra_columns"]:
                err("extra_columns", f"Row has {r['width']} columns; expected 1.")
            if not ident:
                err("required", "Student identifier is required.")
            else:
                member = by_number.get(ident) or by_username.get(ident)
                if member is None:
                    err(
                        "not_in_program",
                        f"'{ident}' is not an active member of this offering's program.",
                    )

            student_id = None
            if member is not None:
                student_id = member.user_id
                if student_id in seen:
                    err("duplicate_row", f"Student '{ident}' appears more than once in the CSV.")
                else:
                    seen.add(student_id)
                    if student_id in enrolled:
                        err("already_enrolled", f"Student '{ident}' is already enrolled.")
                if not member.user.is_active:
                    err("inactive_student", f"Student account '{ident}' is not active.")
                if student_id not in has_student_role:
                    err(
                        "missing_student_role",
                        f"Student '{ident}' has no active student role in this offering.",
                    )

            if not row_errors:
                action = "enroll"
            elif all(e["code"] in DUPLICATE_CODES for e in row_errors):
                action = "duplicate"
            else:
                action = "invalid"
            counts[action] += 1
            errors.extend(row_errors)
            rows.append(
                {
                    "row_number": r["row_number"],
                    "student_identifier": ident,
                    "student_id": str(student_id) if student_id is not None else None,
                    "action": action,
                    "errors": row_errors,
                }
            )

        return {
            "offering": str(offering.pk),
            "sanitized_filename": sanitize_filename(filename),
            "file_checksum": compute_csv_checksum(csv_text),
            "roster_fingerprint": compute_roster_fingerprint(offering),
            "expected_input_revision": offering.input_revision,
            "total_rows": len(rows),
            "valid_rows": counts["enroll"],
            "duplicate_rows": counts["duplicate"],
            "invalid_rows": counts["invalid"],
            "can_apply": counts["enroll"] > 0,
            "errors": errors,
            "rows": rows,
        }

    @transaction.atomic
    def apply(
        self,
        *,
        actor: Any,
        offering: CourseOffering,
        csv_text: str,
        file_checksum: str,
        roster_fingerprint: str,
        expected_input_revision: int | None = None,
        filename: str = "",
    ) -> dict[str, Any]:
        """Enroll every valid row or nothing. Duplicate/invalid rows are skipped and reported."""
        effective_actor = actor if actor is not None else self.actor
        computed = compute_csv_checksum(csv_text)
        if computed != file_checksum.strip().lower():
            raise ValidationError(
                {"file_checksum": "CSV content does not match the provided file checksum."}
            )

        locked = CourseOffering.objects.select_for_update().get(pk=offering.pk)

        if expected_input_revision is not None and locked.input_revision != expected_input_revision:
            raise RosterImportConflict(
                code="stale_preview",
                detail="The offering changed since the preview. Re-run the preview and retry.",
            )
        if compute_roster_fingerprint(locked) != roster_fingerprint:
            raise RosterImportConflict(
                code="stale_preview",
                detail="The roster changed since the preview. Re-run the preview and retry.",
            )

        report = self.preview(offering=locked, csv_text=csv_text, filename=filename)
        to_enroll = [r for r in report["rows"] if r["action"] == "enroll"]
        if not to_enroll:
            raise ValidationError(
                {
                    "detail": "Roster import has no valid rows; no enrollments were written.",
                    "errors": report["errors"],
                }
            )

        users = {
            str(u.pk): u
            for u in get_user_model().objects.filter(pk__in=[r["student_id"] for r in to_enroll])
        }
        for row in to_enroll:
            # Reuse EnrollmentService so role/active checks, status events and
            # revision bumps stay in one place. Any failure rolls back everything.
            self.enrollment_service.create(
                offering=locked, student=users[row["student_id"]], actor=effective_actor
            )

        locked.refresh_from_db(fields=["input_revision"])
        skipped = [
            {
                "row_number": r["row_number"],
                "student_identifier": r["student_identifier"],
                "action": r["action"],
                "errors": r["errors"],
            }
            for r in report["rows"]
            if r["action"] != "enroll"
        ]
        result = {
            "offering": str(locked.pk),
            "file_checksum": computed,
            "sanitized_filename": report["sanitized_filename"],
            "total_rows": report["total_rows"],
            "enrolled_count": len(to_enroll),
            "duplicate_count": report["duplicate_rows"],
            "invalid_count": report["invalid_rows"],
            "skipped_rows": skipped,
            "resulting_input_revision": locked.input_revision,
        }
        AuditEvent.objects.create(
            actor=effective_actor,
            scope=Scope.objects.get(pk=locked.pk),
            action="roster.csv_imported",
            metadata={
                "scope_type": Scope.Kind.OFFERING,
                "offering_id": str(locked.pk),
                "program_id": str(locked.program_id),
                "entity_type": "roster_import",
                "entity_id": computed,
                "file_checksum": computed,
                "sanitized_filename": report["sanitized_filename"],
                "total_rows": report["total_rows"],
                "enrolled_count": len(to_enroll),
                "duplicate_count": report["duplicate_rows"],
                "invalid_count": report["invalid_rows"],
                "resulting_input_revision": locked.input_revision,
            },
        )
        return result
