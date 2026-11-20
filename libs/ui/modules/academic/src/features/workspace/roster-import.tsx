'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import type { ChangeEvent } from 'react';
import { useId, useState } from 'react';
import { ApiError } from '@outcometrik/api';
import { errorMessage } from '@outcometrik/access';
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Field,
  FieldGroup,
  FieldLabel,
  Input,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@outcometrik/ui';
import {
  applyRosterImport,
  getRosterImportTemplate,
  previewRosterImport,
  type RosterImportApplyResult,
  type RosterImportPreviewReport,
  type RosterImportRowAction,
} from './api';

export function canApplyRosterImport(
  report: RosterImportPreviewReport | null,
  csvText: string,
  previewedCsvText: string,
): boolean {
  if (!report || !report.can_apply || report.valid_rows <= 0) {
    return false;
  }
  return csvText.length > 0 && csvText === previewedCsvText;
}

function actionBadgeVariant(
  action: RosterImportRowAction,
): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (action === 'enroll') return 'default';
  if (action === 'duplicate') return 'secondary';
  return 'destructive';
}

export interface RosterCsvImportPanelProps {
  offeringId: string;
  offeringLabel?: string;
  onImported?: (result: RosterImportApplyResult) => void | Promise<void>;
}

export function RosterCsvImportPanel({
  offeringId,
  offeringLabel,
  onImported,
}: RosterCsvImportPanelProps) {
  const queryClient = useQueryClient();
  const fileInputId = useId();
  const csvTextareaId = useId();

  const [csvText, setCsvText] = useState('');
  const [filename, setFilename] = useState('roster.csv');
  const [previewReport, setPreviewReport] =
    useState<RosterImportPreviewReport | null>(null);
  const [previewedCsvText, setPreviewedCsvText] = useState('');
  const [applyResult, setApplyResult] =
    useState<RosterImportApplyResult | null>(null);
  const [conflictMessage, setConflictMessage] = useState('');

  const loadTemplate = useMutation({
    mutationFn: () => getRosterImportTemplate(offeringId),
    onSuccess: (template) => {
      setCsvText(template.sample_csv);
      setFilename('roster.csv');
      setPreviewReport(null);
      setPreviewedCsvText('');
      setApplyResult(null);
      setConflictMessage('');
    },
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      previewRosterImport({
        offering: offeringId,
        csv_text: csvText,
        filename,
      }),
    onMutate: () => {
      setConflictMessage('');
      setApplyResult(null);
    },
    onSuccess: (report) => {
      setPreviewReport(report);
      setPreviewedCsvText(csvText);
    },
  });

  const applyMutation = useMutation({
    mutationFn: () => {
      if (!previewReport) {
        throw new Error('Preview must run before applying roster import.');
      }
      return applyRosterImport({
        offering: offeringId,
        csv_text: csvText,
        file_checksum: previewReport.file_checksum,
        roster_fingerprint: previewReport.roster_fingerprint,
        expected_input_revision: previewReport.expected_input_revision,
        filename,
      });
    },
    onMutate: () => {
      setConflictMessage('');
    },
    onSuccess: async (result) => {
      setApplyResult(result);
      setPreviewReport(null);
      setPreviewedCsvText('');
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['academic', 'coordinator'] }),
        queryClient.invalidateQueries({ queryKey: ['academic', 'instructor'] }),
      ]);
      await onImported?.(result);
    },
    onError: (error) => {
      if (error instanceof ApiError && error.kind === 'conflict') {
        setConflictMessage(
          'Stale roster preview (HTTP 409): the offering roster or revision changed after your preview. Re-run preview to refresh the fingerprint before applying again.',
        );
        setPreviewReport(null);
        setPreviewedCsvText('');
      }
    },
  });

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    const text = await file.text();
    setCsvText(text);
    setPreviewReport(null);
    setPreviewedCsvText('');
    setApplyResult(null);
    setConflictMessage('');
  }

  const busy =
    loadTemplate.isPending ||
    previewMutation.isPending ||
    applyMutation.isPending;

  const applyEnabled =
    canApplyRosterImport(previewReport, csvText, previewedCsvText) && !busy;

  return (
    <Card>
      <CardHeader className="flex flex-wrap items-start justify-between gap-4 sm:flex-row">
        <div>
          <CardTitle>
            Roster CSV Import{offeringLabel ? ` · ${offeringLabel}` : ''}
          </CardTitle>
          <CardDescription>
            Preview UTF-8 CSV rosters (required column:{' '}
            <code>student_identifier</code>; up to 1 MB / 2,000 rows). Preview
            writes nothing; apply enrolls valid rows atomically and reports
            duplicate or invalid rows.
          </CardDescription>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => loadTemplate.mutate()}
          disabled={busy}
        >
          {loadTemplate.isPending
            ? 'Loading template…'
            : 'Load sample CSV template'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor={fileInputId}>Upload roster CSV (.csv)</FieldLabel>
            <Input
              id={fileInputId}
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => void handleFileChange(event)}
              disabled={busy}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor={csvTextareaId}>
              CSV content (column: student_identifier)
            </FieldLabel>
            <textarea
              id={csvTextareaId}
              className="min-h-32 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={csvText}
              onChange={(event) => {
                setCsvText(event.target.value);
                setPreviewReport(null);
                setPreviewedCsvText('');
                setApplyResult(null);
                setConflictMessage('');
              }}
              placeholder={'student_identifier\nS1001\nstudent_username'}
              disabled={busy}
            />
          </Field>
        </FieldGroup>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="secondary"
            onClick={() => previewMutation.mutate()}
            disabled={busy || !csvText.trim()}
          >
            {previewMutation.isPending ? 'Previewing…' : 'Preview roster CSV'}
          </Button>
          <Button
            type="button"
            onClick={() => applyMutation.mutate()}
            disabled={!applyEnabled}
          >
            {applyMutation.isPending
              ? 'Importing…'
              : `Confirm & import${
                  previewReport && previewReport.valid_rows > 0
                    ? ` (${previewReport.valid_rows} valid)`
                    : ''
                }`}
          </Button>
        </div>

        {loadTemplate.isError && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Unable to load template</AlertTitle>
            <AlertDescription>
              {errorMessage(loadTemplate.error)}
            </AlertDescription>
          </Alert>
        )}

        {previewMutation.isError && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Preview failed</AlertTitle>
            <AlertDescription>
              {errorMessage(previewMutation.error)}
            </AlertDescription>
          </Alert>
        )}

        {conflictMessage && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Preview is stale</AlertTitle>
            <AlertDescription>{conflictMessage}</AlertDescription>
          </Alert>
        )}

        {applyMutation.isError && !conflictMessage && (
          <Alert variant="destructive" role="alert">
            <AlertTitle>Import failed</AlertTitle>
            <AlertDescription>
              {errorMessage(applyMutation.error)}
            </AlertDescription>
          </Alert>
        )}

        {applyResult && (
          <Alert role="status">
            <AlertTitle>Roster import applied</AlertTitle>
            <AlertDescription>
              Enrolled {applyResult.enrolled_count} student
              {applyResult.enrolled_count === 1 ? '' : 's'} from{' '}
              <code>{applyResult.sanitized_filename}</code> (
              {applyResult.duplicate_count} duplicate,{' '}
              {applyResult.invalid_count} invalid skipped; revision{' '}
              {applyResult.resulting_input_revision}).
            </AlertDescription>
          </Alert>
        )}

        {previewReport && (
          <div className="space-y-3" aria-live="polite">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="default">
                {previewReport.valid_rows} to enroll
              </Badge>
              <Badge variant="secondary">
                {previewReport.duplicate_rows} duplicate
              </Badge>
              <Badge variant="destructive">
                {previewReport.invalid_rows} invalid
              </Badge>
              <Badge variant="outline">
                {previewReport.total_rows} total rows
              </Badge>
            </div>
            {!previewReport.can_apply && (
              <p className="text-sm text-muted-foreground" role="status">
                No valid rows are eligible to enroll. Resolve invalid or
                duplicate rows and preview again.
              </p>
            )}
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Row</TableHead>
                  <TableHead>Student identifier</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead>Details</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {previewReport.rows.map((row) => (
                  <TableRow key={row.row_number}>
                    <TableCell>{row.row_number}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {row.student_identifier || '—'}
                    </TableCell>
                    <TableCell>
                      <Badge variant={actionBadgeVariant(row.action)}>
                        {row.action}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-sm">
                      {row.errors.length > 0
                        ? row.errors
                            .map((err) => `${err.code}: ${err.message}`)
                            .join('; ')
                        : 'Ready to enroll'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function RosterCsvImportDialog({
  offeringId,
  offeringLabel,
}: {
  offeringId: string;
  offeringLabel: string;
}) {
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          Import roster CSV
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import roster · {offeringLabel}</DialogTitle>
          <DialogDescription>
            Preview and atomically enroll eligible students from a CSV roster.
          </DialogDescription>
        </DialogHeader>
        <RosterCsvImportPanel
          offeringId={offeringId}
          offeringLabel={offeringLabel}
        />
      </DialogContent>
    </Dialog>
  );
}
