import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import App, { reviewErrors } from './App';
import type { FormDefinition, OcrResponse } from './types';

const definition: FormDefinition = {
  formType: 'MOE_FAS', formVersion: '2026-10', pageCount: 3,
  fields: [
    { id: 'applicant_name', label: 'Name', page: 1, section: 'Applicant', dataType: 'string', required: true },
    { id: 'applicant_date_of_birth', label: 'Date of Birth', page: 1, section: 'Applicant', dataType: 'date', required: true },
  ],
};
const result: OcrResponse = {
  requestId: 'one', schemaVersion: '2.0', status: 'REVIEW_REQUIRED', formType: 'MOE_FAS',
  formVersion: '2026-10', pageCount: 3, processedPages: [1, 2, 3], templateMatch: true,
  ocrModel: 'RapidOCR', processingSeconds: 2, ocrSeconds: 1, issues: [], imageQuality: {},
  formValidation: {}, validation: {}, canReview: true, requiresRecapture: false,
  requiresNewForm: false, transcripts: {}, fields: {
    applicant_name: { value: 'Ethan', rawValue: 'Ethan', status: 'EXTRACTED', issues: [] },
    applicant_date_of_birth: { value: null, rawValue: null, status: 'EMPTY', issues: [] },
  },
};
const mockExtract = vi.fn();
vi.mock('./api', () => ({ getFormDefinition: vi.fn(async () => definition), extractOcr: (...args: unknown[]) => mockExtract(...args) }));

beforeEach(() => { mockExtract.mockReset(); });
afterEach(cleanup);

describe('review flow', () => {
  it('validates required fields and a real DD/MM/YYYY date', () => {
    expect(reviewErrors(definition.fields, { applicant_name: '', applicant_date_of_birth: '31/02/2024' })).toEqual({
      applicant_name: 'This field is required.', applicant_date_of_birth: 'Use a real date in DD/MM/YYYY format.',
    });
    expect(reviewErrors(definition.fields, { applicant_name: 'Ethan', applicant_date_of_birth: '29/02/2024' })).toEqual({});
  });

  it('fills extracted values and allows manual correction', async () => {
    mockExtract.mockResolvedValue(result);
    render(<App />);
    await screen.findByText('2 fields across 3 pages');
    const input = screen.getByLabelText('Choose form files');
    fireEvent.change(input, { target: { files: [new File(['%PDF- demo'], 'form.pdf', { type: 'application/pdf' })] } });
    fireEvent.click(screen.getByText('Process document'));
    await waitFor(() => expect(screen.getByDisplayValue('Ethan')).toBeInTheDocument());
    fireEvent.change(screen.getByPlaceholderText('DD/MM/YYYY'), { target: { value: '29/02/2024' } });
    fireEvent.click(screen.getByText('Confirm reviewed values'));
    expect(screen.getByText('Download reviewed JSON ↓')).toBeInTheDocument();
  });

  it('ignores a previous response after file replacement', async () => {
    let resolvePrevious!: (value: OcrResponse) => void;
    mockExtract.mockImplementationOnce(() => new Promise<OcrResponse>(resolve => { resolvePrevious = resolve; }));
    render(<App />);
    await screen.findByText('2 fields across 3 pages');
    const input = screen.getByLabelText('Choose form files');
    fireEvent.change(input, { target: { files: [new File(['%PDF- one'], 'one.pdf', { type: 'application/pdf' })] } });
    fireEvent.click(screen.getByText('Process document'));
    fireEvent.change(input, { target: { files: [new File(['%PDF- two'], 'two.pdf', { type: 'application/pdf' })] } });
    resolvePrevious(result);
    await waitFor(() => expect(screen.getByText('two.pdf')).toBeInTheDocument());
    expect(screen.queryByDisplayValue('Ethan')).not.toBeInTheDocument();
  });

  it('shows recapture guidance and leaves unreadable values empty', async () => {
    mockExtract.mockResolvedValue({ ...result, status: 'RECAPTURE_REQUIRED', requiresRecapture: true,
      fields: { ...result.fields, applicant_name: { value: null, rawValue: null, status: 'UNREADABLE', issues: [] } } });
    render(<App />);
    await screen.findByText('2 fields across 3 pages');
    fireEvent.change(screen.getByLabelText('Choose form files'), { target: { files: [new File(['%PDF- demo'], 'form.pdf', { type: 'application/pdf' })] } });
    fireEvent.click(screen.getByText('Process document'));
    await screen.findByText(/Some required regions were not readable/);
    expect(screen.queryByDisplayValue('Ethan')).not.toBeInTheDocument();
  });

  it('reports an OCR API failure without showing a stale review', async () => {
    mockExtract.mockRejectedValue(new Error('OCR service is temporarily unavailable.'));
    render(<App />);
    await screen.findByText('2 fields across 3 pages');
    fireEvent.change(screen.getByLabelText('Choose form files'), { target: { files: [new File(['%PDF- demo'], 'form.pdf', { type: 'application/pdf' })] } });
    fireEvent.click(screen.getByText('Process document'));
    await screen.findByText('OCR service is temporarily unavailable.');
    expect(screen.queryByText('Confirm reviewed values')).not.toBeInTheDocument();
  });
});
