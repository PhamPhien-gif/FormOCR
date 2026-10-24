export type FormField = { id: string; label: string; page: number; section: string; dataType: string; required: boolean };
export type FormDefinition = { formType: string; formVersion: string; pageCount: number; fields: FormField[] };
export type Issue = { code: string; message: string; severity: string; field?: string | null };
export type OcrField = { value: string | null; rawValue: string | null; status: string; issues: Issue[]; evidence?: unknown };
export type OcrResponse = {
  requestId: string; schemaVersion: string; status: string; formType: string; formVersion: string;
  pageCount: number; processedPages: number[]; templateMatch: boolean; ocrModel: string;
  processingSeconds: number; ocrSeconds: number; fields: Record<string, OcrField>;
  issues: Issue[]; imageQuality: unknown; formValidation: unknown; validation: unknown;
  canReview: boolean; requiresRecapture: boolean; requiresNewForm: boolean;
  transcripts: Record<string, string[]>;
};
