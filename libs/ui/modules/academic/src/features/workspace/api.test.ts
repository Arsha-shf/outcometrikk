import { afterEach, expect, it, vi } from 'vitest';
import { ApiError } from '@outcometrik/api';
import {
  applyRosterImport,
  getInstructorWorkspace,
  getRosterImportTemplate,
  getStudentWorkspace,
  previewRosterImport,
} from './api';

afterEach(() => vi.unstubAllGlobals());

it('parses assigned instructor offerings and roster rows', async () => {
  const fetcher = vi.fn().mockResolvedValue(
    Response.json({
      offerings: [
        {
          id: 'offering-1',
          label: 'CSE 301 · 01',
          course: 'Algorithms',
          program: 'Computer Science',
          term: '2026 Fall',
          roster: [
            { enrollment_id: 'enrollment-1', student_id: 7, name: 'Ada', status: 'enrolled' },
          ],
        },
      ],
    }),
  );
  vi.stubGlobal('fetch', fetcher);
  const result = await getInstructorWorkspace();
  expect(result.offerings[0].roster[0].name).toBe('Ada');
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/workspaces/instructor/');
});

it('rejects malformed student course data and preserves cancellation', async () => {
  const fetcher = vi.fn().mockResolvedValue(Response.json({ courses: [{ course: 'leak' }], outcomes: [] }));
  vi.stubGlobal('fetch', fetcher);
  await expect(getStudentWorkspace()).rejects.toBeInstanceOf(ApiError);
  const controller = new AbortController();
  fetcher.mockResolvedValue(Response.json({ courses: [], outcomes: [] }));
  await getStudentWorkspace(controller.signal);
  expect(fetcher.mock.calls[1][1].signal).toBeInstanceOf(AbortSignal);
});

it('fetches and validates roster import template, preview, and apply responses', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(
      Response.json({
        offering_id: 'off-1',
        columns: ['student_identifier'],
        required_columns: ['student_identifier'],
        max_bytes: 1048576,
        max_rows: 2000,
        sample_csv: 'student_identifier\nR1001\n',
      }),
    )
    .mockResolvedValueOnce(
      Response.json({
        offering: 'off-1',
        sanitized_filename: 'roster.csv',
        file_checksum: 'a'.repeat(64),
        roster_fingerprint: 'b'.repeat(64),
        expected_input_revision: 2,
        total_rows: 3,
        valid_rows: 1,
        duplicate_rows: 1,
        invalid_rows: 1,
        can_apply: true,
        errors: [
          {
            row_number: 2,
            column: 'student_identifier',
            code: 'already_enrolled',
            message: "Student 'R1002' is already enrolled.",
          },
          {
            row_number: 3,
            column: 'student_identifier',
            code: 'not_in_program',
            message: "'ghost' is not an active member of this offering's program.",
          },
        ],
        rows: [
          {
            row_number: 1,
            student_identifier: 'R1001',
            student_id: '10',
            action: 'enroll',
            errors: [],
          },
          {
            row_number: 2,
            student_identifier: 'R1002',
            student_id: '11',
            action: 'duplicate',
            errors: [
              {
                row_number: 2,
                column: 'student_identifier',
                code: 'already_enrolled',
                message: "Student 'R1002' is already enrolled.",
              },
            ],
          },
          {
            row_number: 3,
            student_identifier: 'ghost',
            student_id: null,
            action: 'invalid',
            errors: [
              {
                row_number: 3,
                column: 'student_identifier',
                code: 'not_in_program',
                message: "'ghost' is not an active member of this offering's program.",
              },
            ],
          },
        ],
      }),
    )
    .mockResolvedValueOnce(
      Response.json(
        {
          offering: 'off-1',
          file_checksum: 'a'.repeat(64),
          sanitized_filename: 'roster.csv',
          total_rows: 3,
          enrolled_count: 1,
          duplicate_count: 1,
          invalid_count: 1,
          skipped_rows: [
            {
              row_number: 2,
              student_identifier: 'R1002',
              action: 'duplicate',
              errors: [
                {
                  row_number: 2,
                  column: 'student_identifier',
                  code: 'already_enrolled',
                  message: "Student 'R1002' is already enrolled.",
                },
              ],
            },
          ],
          resulting_input_revision: 3,
        },
        { status: 201 },
      ),
    );
  vi.stubGlobal('document', { cookie: 'csrftoken=test-token' });
  vi.stubGlobal('fetch', fetcher);

  const controller = new AbortController();
  const template = await getRosterImportTemplate('off-1', controller.signal);
  expect(template.required_columns).toEqual(['student_identifier']);
  expect(fetcher.mock.calls[0][0]).toBe('/api/v1/enrollments/import/template/?offering=off-1');
  expect(fetcher.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal);

  const preview = await previewRosterImport({
    offering: 'off-1',
    csv_text: 'student_identifier\nR1001\nR1002\nghost\n',
    filename: 'roster.csv',
  });
  expect(preview.valid_rows).toBe(1);
  expect(preview.duplicate_rows).toBe(1);
  expect(preview.invalid_rows).toBe(1);
  expect(fetcher.mock.calls[1][0]).toBe('/api/v1/enrollments/import/preview/');

  const applied = await applyRosterImport({
    offering: 'off-1',
    csv_text: 'student_identifier\nR1001\nR1002\nghost\n',
    file_checksum: preview.file_checksum,
    roster_fingerprint: preview.roster_fingerprint,
    expected_input_revision: preview.expected_input_revision,
    filename: 'roster.csv',
  });
  expect(applied.enrolled_count).toBe(1);
  expect(applied.resulting_input_revision).toBe(3);
  expect(fetcher.mock.calls[2][0]).toBe('/api/v1/enrollments/import/apply/');
});

it('rejects malformed roster import payloads', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ offering_id: 'off-1' }))
    .mockResolvedValueOnce(Response.json({ offering: 'off-1', rows: 'bad' }))
    .mockResolvedValueOnce(Response.json({ offering: 'off-1', enrolled_count: 'one' }));
  vi.stubGlobal('document', { cookie: 'csrftoken=test-token' });
  vi.stubGlobal('fetch', fetcher);

  await expect(getRosterImportTemplate('off-1')).rejects.toBeInstanceOf(ApiError);
  await expect(
    previewRosterImport({ offering: 'off-1', csv_text: 'student_identifier\nR1001\n' }),
  ).rejects.toBeInstanceOf(ApiError);
  await expect(
    applyRosterImport({
      offering: 'off-1',
      csv_text: 'student_identifier\nR1001\n',
      file_checksum: 'a'.repeat(64),
      roster_fingerprint: 'b'.repeat(64),
    }),
  ).rejects.toBeInstanceOf(ApiError);
});
