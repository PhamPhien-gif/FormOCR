import type { FormDefinition, OcrResponse } from './types';

const baseUrl = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5100').replace(/\/$/, '');

async function parseResponse<T>(response: Response): Promise<T> {
  let payload: unknown;
  try { payload = await response.json(); } catch { throw new Error('The server returned an unreadable response.'); }
  if (!response.ok) {
    const error = payload as { message?: string };
    throw new Error(error?.message || `Request failed (${response.status}).`);
  }
  return payload as T;
}

export async function getFormDefinition(signal?: AbortSignal): Promise<FormDefinition> {
  return parseResponse<FormDefinition>(await fetch(`${baseUrl}/api/v1/fas/form`, { signal }));
}

export async function extractOcr(files: File[], definition: FormDefinition, signal?: AbortSignal): Promise<OcrResponse> {
  const body = new FormData();
  files.forEach(file => body.append('file', file));
  body.append('form_type', definition.formType);
  body.append('form_version', definition.formVersion);
  return parseResponse<OcrResponse>(await fetch(`${baseUrl}/api/v1/fas/ocr`, { method: 'POST', body, signal }));
}
