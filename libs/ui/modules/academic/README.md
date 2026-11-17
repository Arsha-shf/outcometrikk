# Academic UI

`@outcometrik/academic` owns coordinator, instructor, and student academic workspaces.
It uses the public session contract from `@outcometrik/access`, shared transport,
and shared UI components.

The instructor dashboard at `/instructor` uses a workspace sidebar with overview and
grades/roster operations. It shows assigned offerings and active roster counts; each
offering opens its gradebook directly. The gradebook at `/instructor/gradebook` remains
available as a standalone route. It selects approved assessments, creates and releases
batches, and records scored/zero/missing/exempt/withdrawn/incomplete results. Instructors
can search the roster, filter students by grade status, see completion counts, correct
grades with optimistic versions, and inspect append-only history. Released-grade entry
and corrections prompt for a reason; inactive enrollments remain visible but cannot be
graded. Loading, empty, save, validation, and conflict states are announced in the
interface. The student dashboard lists only grades returned by the released-grade API.
Assessment authoring is not part of GRD-01; the gradebook reads approved assessments
from the scoped API and displays an empty state when curriculum setup is incomplete.
The coordinator dashboard shows memberships and offering counts inside managed
programs. Published outcome profiles remain a downstream workflow.

The gradebook consumes `GET /api/v1/assessments/?offering={id}`, grade-batch list/create/release,
and grade list/create/correct/history endpoints. Approved assessments are visible only to staff
with `grades.edit` on the offering. Student grade lists expose only released records for the
signed-in student.

For request and authorization details, see the [gradebook API contract](../../../../apps/api/README.md#gradebook-api-grd-01).
The assessment model is currently a CUR-01 stub. Versioned syllabus integration and
publication staleness remain downstream work; the UI does not implement them.
