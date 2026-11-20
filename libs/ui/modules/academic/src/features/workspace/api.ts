import { ApiError, request } from '@outcometrik/api';

export interface InstructorOffering {
  id: string;
  label: string;
  course: string;
  program: string;
  term: string;
  input_revision?: number;
  roster: { enrollment_id: string; student_id?: number; name: string; status: string }[];
}
export interface StudentCourse {
  enrollment_id: string;
  offering_id: string;
  course_code: string;
  course: string;
  program: string;
  term: string;
  section: string;
  enrollment_status: string;
}
export interface CoordinatorWorkspace {
  programs: { id: string; label: string; department: string }[];
  offerings: { id: string; program_id: string; label: string; course: string; term: string; enrolled: number }[];
  students: { id: number; username: string; first_name: string; last_name: string; program_id: string; student_number: string; membership_status: string }[];
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function isInstructorOffering(value: unknown): value is InstructorOffering {
  return (
    isRecord(value) &&
    typeof value.id === 'string' &&
    typeof value.label === 'string' &&
    typeof value.course === 'string' &&
    typeof value.program === 'string' &&
    typeof value.term === 'string' &&
    (value.input_revision === undefined || typeof value.input_revision === 'number') &&
    Array.isArray(value.roster) &&
    value.roster.every(
      (row) =>
        isRecord(row) &&
        typeof row.enrollment_id === 'string' &&
        (row.student_id === undefined || typeof row.student_id === 'number') &&
        typeof row.name === 'string' &&
        typeof row.status === 'string',
    )
  );
}
function isStudentCourse(value: unknown): value is StudentCourse {
  return (
    isRecord(value) &&
    ['enrollment_id', 'offering_id', 'course_code', 'course', 'program', 'term', 'section', 'enrollment_status'].every(
      (key) => typeof value[key] === 'string',
    )
  );
}
function isCoordinatorWorkspace(value: unknown): value is CoordinatorWorkspace {
  return (
    isRecord(value) &&
    Array.isArray(value.programs) &&
    value.programs.every((row) => isRecord(row) && typeof row.id === 'string' && typeof row.label === 'string' && typeof row.department === 'string') &&
    Array.isArray(value.offerings) &&
    value.offerings.every((row) => isRecord(row) && typeof row.id === 'string' && typeof row.program_id === 'string' && typeof row.label === 'string' && typeof row.course === 'string' && typeof row.term === 'string' && typeof row.enrolled === 'number') &&
    Array.isArray(value.students) &&
    value.students.every((row) => isRecord(row) && typeof row.id === 'number' && typeof row.username === 'string' && typeof row.first_name === 'string' && typeof row.last_name === 'string' && typeof row.program_id === 'string' && typeof row.student_number === 'string' && typeof row.membership_status === 'string')
  );
}
export async function getCoordinatorWorkspace(signal?: AbortSignal) {
  const data: unknown = await request('/api/v1/workspaces/coordinator/', { signal, cache: 'no-store' });
  if (!isCoordinatorWorkspace(data)) throw new ApiError('unexpected', 200);
  return data;
}
export async function getInstructorWorkspace(signal?: AbortSignal) {
  const data: unknown = await request('/api/v1/workspaces/instructor/', { signal, cache: 'no-store' });
  if (!isRecord(data) || !Array.isArray(data.offerings) || !data.offerings.every(isInstructorOffering))
    throw new ApiError('unexpected', 200);
  return { offerings: data.offerings };
}
export async function getStudentWorkspace(signal?: AbortSignal) {
  const data: unknown = await request('/api/v1/workspaces/student/', { signal, cache: 'no-store' });
  if (!isRecord(data) || !Array.isArray(data.courses) || !data.courses.every(isStudentCourse) || !Array.isArray(data.outcomes))
    throw new ApiError('unexpected', 200);
  return { courses: data.courses, outcomes: data.outcomes };
}

export interface RosterImportTemplate {
  offering_id: string;
  columns: string[];
  required_columns: string[];
  max_bytes: number;
  max_rows: number;
  sample_csv: string;
}

export interface RosterImportRowError {
  row_number: number;
  column: string;
  code: string;
  message: string;
}

export type RosterImportRowAction = 'enroll' | 'duplicate' | 'invalid';

export interface RosterImportPreviewRow {
  row_number: number;
  student_identifier: string;
  student_id: string | null;
  action: RosterImportRowAction;
  errors: RosterImportRowError[];
}

export interface RosterImportPreviewReport {
  offering: string;
  sanitized_filename: string;
  file_checksum: string;
  roster_fingerprint: string;
  expected_input_revision: number;
  total_rows: number;
  valid_rows: number;
  duplicate_rows: number;
  invalid_rows: number;
  can_apply: boolean;
  errors: RosterImportRowError[];
  rows: RosterImportPreviewRow[];
}

export interface RosterImportSkippedRow {
  row_number: number;
  student_identifier: string;
  action: 'duplicate' | 'invalid';
  errors: RosterImportRowError[];
}

export interface RosterImportApplyResult {
  offering: string;
  file_checksum: string;
  sanitized_filename: string;
  total_rows: number;
  enrolled_count: number;
  duplicate_count: number;
  invalid_count: number;
  skipped_rows: RosterImportSkippedRow[];
  resulting_input_revision: number;
}

export interface RosterImportPreviewRequest {
  offering: string;
  csv_text: string;
  filename?: string;
}

export interface RosterImportApplyRequest {
  offering: string;
  csv_text: string;
  file_checksum: string;
  roster_fingerprint: string;
  expected_input_revision?: number;
  filename?: string;
}

const ROSTER_ACTIONS = new Set<RosterImportRowAction>(['enroll', 'duplicate', 'invalid']);

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isRosterImportRowError(value: unknown): value is RosterImportRowError {
  return (
    isRecord(value) &&
    typeof value.row_number === 'number' &&
    typeof value.column === 'string' &&
    typeof value.code === 'string' &&
    typeof value.message === 'string'
  );
}

function isRosterImportRowAction(value: unknown): value is RosterImportRowAction {
  return typeof value === 'string' && ROSTER_ACTIONS.has(value as RosterImportRowAction);
}

function isRosterImportTemplate(value: unknown): value is RosterImportTemplate {
  return (
    isRecord(value) &&
    typeof value.offering_id === 'string' &&
    isStringArray(value.columns) &&
    isStringArray(value.required_columns) &&
    typeof value.max_bytes === 'number' &&
    typeof value.max_rows === 'number' &&
    typeof value.sample_csv === 'string'
  );
}

function isRosterImportPreviewRow(value: unknown): value is RosterImportPreviewRow {
  return (
    isRecord(value) &&
    typeof value.row_number === 'number' &&
    typeof value.student_identifier === 'string' &&
    (typeof value.student_id === 'string' || value.student_id === null) &&
    isRosterImportRowAction(value.action) &&
    Array.isArray(value.errors) &&
    value.errors.every(isRosterImportRowError)
  );
}

function isRosterImportPreviewReport(value: unknown): value is RosterImportPreviewReport {
  return (
    isRecord(value) &&
    typeof value.offering === 'string' &&
    typeof value.sanitized_filename === 'string' &&
    typeof value.file_checksum === 'string' &&
    typeof value.roster_fingerprint === 'string' &&
    typeof value.expected_input_revision === 'number' &&
    typeof value.total_rows === 'number' &&
    typeof value.valid_rows === 'number' &&
    typeof value.duplicate_rows === 'number' &&
    typeof value.invalid_rows === 'number' &&
    typeof value.can_apply === 'boolean' &&
    Array.isArray(value.errors) &&
    value.errors.every(isRosterImportRowError) &&
    Array.isArray(value.rows) &&
    value.rows.every(isRosterImportPreviewRow)
  );
}

function isRosterImportSkippedRow(value: unknown): value is RosterImportSkippedRow {
  return (
    isRecord(value) &&
    typeof value.row_number === 'number' &&
    typeof value.student_identifier === 'string' &&
    (value.action === 'duplicate' || value.action === 'invalid') &&
    Array.isArray(value.errors) &&
    value.errors.every(isRosterImportRowError)
  );
}

function isRosterImportApplyResult(value: unknown): value is RosterImportApplyResult {
  return (
    isRecord(value) &&
    typeof value.offering === 'string' &&
    typeof value.file_checksum === 'string' &&
    typeof value.sanitized_filename === 'string' &&
    typeof value.total_rows === 'number' &&
    typeof value.enrolled_count === 'number' &&
    typeof value.duplicate_count === 'number' &&
    typeof value.invalid_count === 'number' &&
    Array.isArray(value.skipped_rows) &&
    value.skipped_rows.every(isRosterImportSkippedRow) &&
    typeof value.resulting_input_revision === 'number'
  );
}

export async function getRosterImportTemplate(offeringId: string, signal?: AbortSignal) {
  const params = new URLSearchParams({ offering: offeringId });
  const data: unknown = await request(`/api/v1/enrollments/import/template/?${params}`, {
    signal,
    cache: 'no-store',
  });
  if (!isRosterImportTemplate(data)) throw new ApiError('unexpected', 200);
  return data;
}

export async function previewRosterImport(
  payload: RosterImportPreviewRequest,
  signal?: AbortSignal,
) {
  const data: unknown = await request('/api/v1/enrollments/import/preview/', {
    method: 'POST',
    body: payload,
    signal,
    cache: 'no-store',
  });
  if (!isRosterImportPreviewReport(data)) throw new ApiError('unexpected', 200);
  return data;
}

export async function applyRosterImport(
  payload: RosterImportApplyRequest,
  signal?: AbortSignal,
) {
  const data: unknown = await request('/api/v1/enrollments/import/apply/', {
    method: 'POST',
    body: payload,
    signal,
    cache: 'no-store',
  });
  if (!isRosterImportApplyResult(data)) throw new ApiError('unexpected', 201);
  return data;
}
