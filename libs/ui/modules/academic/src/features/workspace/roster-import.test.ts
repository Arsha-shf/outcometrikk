import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

vi.mock('@outcometrik/access', () => ({
  errorMessage: () => 'Request failed',
}));
vi.mock('@tanstack/react-query', () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({
    isPending: false,
    isError: false,
    error: null,
    mutate: vi.fn(),
  }),
}));

import type { RosterImportPreviewReport } from './api';
import { canApplyRosterImport, RosterCsvImportPanel } from './roster-import';

const SAMPLE_REPORT: RosterImportPreviewReport = {
  offering: 'off-1',
  sanitized_filename: 'roster.csv',
  file_checksum: 'a'.repeat(64),
  roster_fingerprint: 'b'.repeat(64),
  expected_input_revision: 1,
  total_rows: 2,
  valid_rows: 1,
  duplicate_rows: 1,
  invalid_rows: 0,
  can_apply: true,
  errors: [],
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
  ],
};

it('only allows apply when preview is fresh, unchanged, and has valid rows', () => {
  const csv = 'student_identifier\nR1001\nR1002\n';
  expect(canApplyRosterImport(null, csv, csv)).toBe(false);
  expect(canApplyRosterImport(SAMPLE_REPORT, csv, csv)).toBe(true);
  expect(canApplyRosterImport(SAMPLE_REPORT, `${csv}R1003\n`, csv)).toBe(false);
  expect(
    canApplyRosterImport(
      { ...SAMPLE_REPORT, valid_rows: 0, can_apply: false },
      csv,
      csv,
    ),
  ).toBe(false);
});

it('renders accessible roster CSV upload, preview, and disabled confirm controls', () => {
  const markup = renderToStaticMarkup(
    createElement(RosterCsvImportPanel, {
      offeringId: 'off-1',
      offeringLabel: 'CSE320 · 01',
    }),
  );
  expect(markup).toContain('Roster CSV Import');
  expect(markup).toContain('CSE320 · 01');
  expect(markup).toContain('Load sample CSV template');
  expect(markup).toContain('Upload roster CSV (.csv)');
  expect(markup).toContain('Preview roster CSV');
  expect(markup).toContain('Confirm &amp; import');
});
