# ROST-01 — Preview and import student rosters

**Blocked by:** ACAD-01, AUTH-01.
**Estimate:** To be estimated by the team.
**Owner/reviewer:** Unassigned; decide at planning based on capacity and skills.

## Epic and PRD traceability

- **Epic:** EPIC-02.
- **PRD:** PRD §11.1 FR-105; §11.3.
- **Out of scope:** No broader permissions, external SIS/LMS, or unapproved policy defaults.

## User story

As a Program coordinator, I want to preview and import an offering roster from CSV, so that I can avoid duplicate or incorrectly scoped enrollments.

## Acceptance criteria

- **Scenario:** Given a coordinator uploads a roster containing valid, duplicate and invalid rows, When they preview and confirm it, Then valid rows are applied atomically, duplicate/invalid rows are identified, and a failed/stale preview writes nothing.

## Contracts and validation

Honor API/domain ownership, scoped authorization, explicit null/error states, and current revisions. Validate input at the boundary and reauthorize writes server-side.

## Implementation tasks

- [ ] Define CSV contract and limits; validate program/offering scope; duplicate detection; atomic apply; audit; tests.
- [ ] Add focused automated tests for success, failure, and scope denial.
- [ ] Document contract and update dependent stories.


## Contract (implemented)

Routes, all under `/api/v1/enrollments/`, all requiring `offering.manage` on the offering:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `import/template/?offering=<id>` | Columns, limits, sample CSV |
| POST | `import/preview/` | Classify rows. Writes nothing |
| POST | `import/apply/` | Enroll valid rows atomically |

**CSV:** one required column, `student_identifier` (program student number or username).
UTF-8, at most 1 MB and 2,000 data rows. Unknown, duplicate or missing headers are rejected (400).

**Row actions:** `enroll`, `duplicate` (`duplicate_row`, `already_enrolled`), or `invalid`
(`required`, `not_in_program`, `inactive_student`, `missing_student_role`, `extra_columns`).
A student must be an active member of the offering's program, have an active `student`
role in the offering, and have an active account. The import never grants roles.

**Apply request:** preview fields `offering`, `csv_text`, `filename`, plus `file_checksum`,
`roster_fingerprint` and optional `expected_input_revision`, all copied from the preview response.

**Outcomes:**
- 201: valid rows enrolled in one transaction. Duplicate and invalid rows are returned in `skipped_rows`.
- 409 `stale_preview`: roster fingerprint or `input_revision` changed since the preview. Nothing is written.
- 400: bad CSV, checksum mismatch, or no valid rows. Nothing is written.
- 403: caller lacks `offering.manage` on this offering.

**Audit:** one `roster.csv_imported` event per successful apply, scoped to the offering.
Enrollment creation reuses `EnrollmentService.create`, so status events and revision bumps are unchanged.