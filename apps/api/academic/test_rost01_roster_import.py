import pytest
from access.models import AuditEvent, RoleAssignment, Scope
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from academic.access_scopes import sync_scope
from academic.models import (
    AcademicTerm,
    Course,
    CourseOffering,
    Department,
    Enrollment,
    EnrollmentStatusEvent,
    Institution,
    Program,
    ProgramCourse,
    ProgramMembership,
)
from academic.services.enrollments import EnrollmentService
from academic.services.grade_import import compute_csv_checksum

PREVIEW = "/api/v1/enrollments/import/preview/"
APPLY = "/api/v1/enrollments/import/apply/"
TEMPLATE = "/api/v1/enrollments/import/template/"


def _grant_role(user, scope_id, role_slug):
    return RoleAssignment.objects.get_or_create(
        user=user, scope_id=scope_id, role_id=role_slug, revoked_at__isnull=True
    )[0]


def _client_for(user):
    client = APIClient()
    if user is not None:
        client.force_authenticate(user=user)
    return client


@pytest.fixture
def roster_world(db):
    User = get_user_model()
    coordinator = User.objects.create_user("rost_coordinator")
    other_coordinator = User.objects.create_user("rost_other_coordinator")
    outsider = User.objects.create_user("rost_outsider")
    s1 = User.objects.create_user("rost_s1")
    s2 = User.objects.create_user("rost_s2")
    already = User.objects.create_user("rost_already")
    no_role = User.objects.create_user("rost_norole")
    non_member = User.objects.create_user("rost_nonmember")

    root = Scope.objects.create(kind=Scope.Kind.INSTITUTION, label="Roster University")
    inst = Institution.objects.create(pk=root.pk, code="ROSU", name="Roster University")
    dept = Department.objects.create(institution=inst, code="CSE", name="Computer Engineering")
    term = AcademicTerm.objects.create(
        institution=inst, year=2026, season="fall", starts_at="2026-09-01", ends_at="2027-01-15"
    )
    course = Course.objects.create(
        home_department=dept, code="CSE320", title="Databases", ects=6, credits=4
    )
    program = Program.objects.create(
        department=dept, code="CSE-BS", title="B.S. CSE", status=Program.Status.ACTIVE
    )
    other_program = Program.objects.create(
        department=dept, code="EE-BS", title="B.S. EE", status=Program.Status.ACTIVE
    )
    sync_scope(program)  # idempotent; guarantees the program Scope row exists
    sync_scope(other_program)
    ProgramCourse.objects.create(
        program=program,
        course=course,
        status=ProgramCourse.Status.APPROVED,
        effective_from="2026-01-01",
    )
    offering = CourseOffering.objects.create(
        program=program, course=course, term=term, section="01"
    )

    # Coordinator role is seeded as "program-coordinator" at PROGRAM scope.
    _grant_role(coordinator, program.pk, "program-coordinator")
    _grant_role(other_coordinator, other_program.pk, "program-coordinator")

    for user, number in (
        (s1, "R1001"),
        (s2, "R1002"),
        (already, "R1003"),
        (no_role, "R1004"),
    ):
        ProgramMembership.objects.create(
            program=program, user=user, student_number=number, status="active"
        )
    for user in (s1, s2, already):
        _grant_role(user, offering.pk, "student")
    _grant_role(non_member, offering.pk, "student")  # has role, but not in the program

    Enrollment.objects.create(offering=offering, student=already)

    return {
        "coordinator": coordinator,
        "other_coordinator": other_coordinator,
        "outsider": outsider,
        "s1": s1,
        "s2": s2,
        "already": already,
        "offering": offering,
    }


# Row notes, in order: valid (student number), valid (username),
# duplicate inside the CSV, already enrolled, no student role in this
# offering, not in program, has role but not a program member.
MIXED_CSV = """\
student_identifier
R1001
rost_s2
R1001
R1003
R1004
ghost
rost_nonmember"""


def _preview(client, offering, csv_text=MIXED_CSV):
    return client.post(
        PREVIEW,
        {"offering": str(offering.pk), "csv_text": csv_text, "filename": "roster.csv"},
        format="json",
    )


def _apply_payload(offering, csv_text, preview):
    return {
        "offering": str(offering.pk),
        "csv_text": csv_text,
        "file_checksum": compute_csv_checksum(csv_text),
        "roster_fingerprint": preview["roster_fingerprint"],
        "expected_input_revision": preview["expected_input_revision"],
        "filename": "roster.csv",
    }


def test_preview_classifies_rows_and_writes_nothing(roster_world):
    offering = roster_world["offering"]
    before = Enrollment.objects.count()
    resp = _preview(_client_for(roster_world["coordinator"]), offering)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_rows"] == 7
    assert data["valid_rows"] == 2
    assert data["duplicate_rows"] == 2
    assert data["invalid_rows"] == 3
    assert data["can_apply"] is True
    actions = [r["action"] for r in data["rows"]]
    assert actions == [
        "enroll",
        "enroll",
        "duplicate",
        "duplicate",
        "invalid",
        "invalid",
        "invalid",
    ]
    codes = {e["code"] for e in data["errors"]}
    assert {"duplicate_row", "already_enrolled", "missing_student_role", "not_in_program"} <= codes
    assert Enrollment.objects.count() == before
    assert AuditEvent.objects.filter(action="roster.csv_imported").count() == 0


def test_template_returns_contract(roster_world):
    resp = _client_for(roster_world["coordinator"]).get(
        f"{TEMPLATE}?offering={roster_world['offering'].pk}"
    )
    assert resp.status_code == 200
    assert resp.json()["required_columns"] == ["student_identifier"]


def test_apply_enrolls_only_valid_rows_and_audits(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()

    resp = client.post(APPLY, _apply_payload(offering, MIXED_CSV, preview), format="json")
    assert resp.status_code == 201
    data = resp.json()
    assert data["enrolled_count"] == 2
    assert data["duplicate_count"] == 2
    assert data["invalid_count"] == 3
    assert len(data["skipped_rows"]) == 5

    enrolled = set(
        Enrollment.objects.filter(offering=offering).values_list("student__username", flat=True)
    )
    assert enrolled == {"rost_already", "rost_s1", "rost_s2"}
    assert EnrollmentStatusEvent.objects.filter(
        enrollment__student=roster_world["s1"], reason="created"
    ).exists()

    audit = AuditEvent.objects.filter(action="roster.csv_imported").get()
    assert audit.actor == roster_world["coordinator"]
    assert audit.scope_id == offering.pk
    assert audit.metadata["enrolled_count"] == 2
    assert audit.metadata["file_checksum"] == compute_csv_checksum(MIXED_CSV)


def test_reapplying_same_csv_after_success_is_stale_and_writes_nothing(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()
    payload = _apply_payload(offering, MIXED_CSV, preview)
    assert client.post(APPLY, payload, format="json").status_code == 201

    count = Enrollment.objects.count()
    resp = client.post(APPLY, payload, format="json")
    assert resp.status_code == 409
    assert resp.json()["code"] == "stale_preview"
    assert Enrollment.objects.count() == count
    assert AuditEvent.objects.filter(action="roster.csv_imported").count() == 1


def test_stale_roster_fingerprint_returns_409_and_writes_nothing(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()

    # A withdrawn enrollment is added between preview and confirm. Withdrawn rows are
    # not eligible, so input_revision does not move; only the fingerprint catches it.
    Enrollment.objects.create(
        offering=offering, student=roster_world["s1"], status=Enrollment.Status.WITHDRAWN
    )
    count = Enrollment.objects.count()

    resp = client.post(APPLY, _apply_payload(offering, MIXED_CSV, preview), format="json")
    assert resp.status_code == 409
    assert resp.json()["code"] == "stale_preview"
    assert Enrollment.objects.count() == count
    assert AuditEvent.objects.filter(action="roster.csv_imported").count() == 0


def test_stale_input_revision_returns_409(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()
    CourseOffering.objects.filter(pk=offering.pk).update(input_revision=9)

    resp = client.post(APPLY, _apply_payload(offering, MIXED_CSV, preview), format="json")
    assert resp.status_code == 409
    assert Enrollment.objects.filter(offering=offering).count() == 1


def test_apply_with_no_valid_rows_writes_nothing(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    csv_text = "student_identifier\nR1003\nghost\n"
    preview = _preview(client, offering, csv_text).json()
    assert preview["can_apply"] is False

    resp = client.post(APPLY, _apply_payload(offering, csv_text, preview), format="json")
    assert resp.status_code == 400
    assert Enrollment.objects.filter(offering=offering).count() == 1
    assert AuditEvent.objects.filter(action="roster.csv_imported").count() == 0


def test_checksum_mismatch_is_rejected(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()
    payload = _apply_payload(offering, MIXED_CSV, preview)
    payload["file_checksum"] = "0" * 64
    assert client.post(APPLY, payload, format="json").status_code == 400
    assert Enrollment.objects.filter(offering=offering).count() == 1


def test_failure_midway_rolls_back_every_enrollment(roster_world, monkeypatch):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    preview = _preview(client, offering).json()

    original = EnrollmentService.create
    calls = {"n": 0}

    def flaky(self, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise ValidationError("boom")
        return original(self, **kwargs)

    monkeypatch.setattr(EnrollmentService, "create", flaky)
    resp = client.post(APPLY, _apply_payload(offering, MIXED_CSV, preview), format="json")
    assert resp.status_code == 400
    assert Enrollment.objects.filter(offering=offering).count() == 1  # only "already"
    assert EnrollmentStatusEvent.objects.filter(enrollment__student=roster_world["s1"]).count() == 0
    assert AuditEvent.objects.filter(action="roster.csv_imported").count() == 0


@pytest.mark.parametrize(
    "bad_csv, fragment",
    [
        ("name\nR1001\n", "Unknown CSV header"),
        ("student_identifier,student_identifier\nR1001,R1001\n", "Duplicate"),
        ("student_identifier\n", "at least one data row"),
        ("   \n", "empty"),
    ],
)
def test_preview_rejects_bad_csv_contract(roster_world, bad_csv, fragment):
    resp = _preview(_client_for(roster_world["coordinator"]), roster_world["offering"], bad_csv)
    assert resp.status_code == 400
    assert fragment in str(resp.json())


def test_scoped_authorization_denies_unauthorized_actors(roster_world):
    offering = roster_world["offering"]
    csv_text = "student_identifier\nR1001\n"
    payload = {
        "offering": str(offering.pk),
        "csv_text": csv_text,
        "file_checksum": compute_csv_checksum(csv_text),
        "roster_fingerprint": "x" * 64,
    }
    anon = _client_for(None)
    assert anon.get(f"{TEMPLATE}?offering={offering.pk}").status_code in (401, 403)
    assert anon.post(PREVIEW, payload, format="json").status_code in (401, 403)
    assert anon.post(APPLY, payload, format="json").status_code in (401, 403)

    # Student, no-role user, and a coordinator of a DIFFERENT program are all denied.
    for actor in (roster_world["s1"], roster_world["outsider"], roster_world["other_coordinator"]):
        client = _client_for(actor)
        assert client.get(f"{TEMPLATE}?offering={offering.pk}").status_code == 403
        assert client.post(PREVIEW, payload, format="json").status_code == 403
        assert client.post(APPLY, payload, format="json").status_code == 403

    assert Enrollment.objects.filter(offering=offering).count() == 1


def test_bom_crlf_default_filename_and_no_store_headers(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    bom_csv = "\ufeffstudent_identifier\r\nR1001\r\n"

    tmpl = client.get(f"{TEMPLATE}?offering={offering.pk}")
    assert tmpl.status_code == 200
    assert tmpl["Cache-Control"] == "no-store"

    preview_resp = client.post(
        PREVIEW,
        {"offering": str(offering.pk), "csv_text": bom_csv, "filename": ""},
        format="json",
    )
    assert preview_resp.status_code == 200
    assert preview_resp["Cache-Control"] == "no-store"
    preview = preview_resp.json()
    assert preview["sanitized_filename"] == "roster.csv"
    assert preview["valid_rows"] == 1
    assert preview["can_apply"] is True

    apply_resp = client.post(
        APPLY,
        {
            "offering": str(offering.pk),
            "csv_text": bom_csv,
            "file_checksum": preview["file_checksum"],
            "roster_fingerprint": preview["roster_fingerprint"],
            "expected_input_revision": preview["expected_input_revision"],
            "filename": "",
        },
        format="json",
    )
    assert apply_resp.status_code == 201
    assert apply_resp["Cache-Control"] == "no-store"
    assert apply_resp.json()["sanitized_filename"] == "roster.csv"


def test_preview_flags_inactive_student_and_extra_columns(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    s1 = roster_world["s1"]
    s1.is_active = False
    s1.save(update_fields=["is_active"])

    csv_text = "student_identifier\nR1001\nrost_s2,unexpected_extra\n"
    resp = _preview(client, offering, csv_text)
    assert resp.status_code == 200
    data = resp.json()
    assert data["valid_rows"] == 0
    assert data["invalid_rows"] == 2
    assert data["can_apply"] is False
    codes = {e["code"] for e in data["errors"]}
    assert {"inactive_student", "extra_columns"} <= codes


def test_template_escapes_formula_prefix_student_number(roster_world):
    offering = roster_world["offering"]
    client = _client_for(roster_world["coordinator"])
    ProgramMembership.objects.filter(program=offering.program, user=roster_world["s1"]).update(
        student_number="=CMD"
    )
    # Ensure s1 is ordered first by student_number ('=' < 'R')
    resp = client.get(f"{TEMPLATE}?offering={offering.pk}")
    assert resp.status_code == 200
    assert resp.json()["sample_csv"] == "student_identifier\n'=CMD\n"


def test_preview_rejects_non_active_offering(roster_world):
    offering = roster_world["offering"]
    offering.status = CourseOffering.Status.ARCHIVED
    offering.save(update_fields=["status"])
    resp = _preview(_client_for(roster_world["coordinator"]), offering)
    assert resp.status_code == 400
    assert "not active" in str(resp.json())
