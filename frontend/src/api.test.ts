import { afterEach, expect, it, vi } from 'vitest';
import { extractOcr } from './api';
import type { FormDefinition } from './types';

afterEach(() => vi.unstubAllGlobals());

it('sends all page images as repeated multipart file fields to the gateway', async () => {
  const request = vi.fn(async (_url: string, init: RequestInit) => {
    const body = init.body as FormData;
    expect(body.getAll('file')).toHaveLength(3);
    expect(body.get('form_type')).toBe('MOE_FAS');
    expect(body.get('form_version')).toBe('2026-10');
    return new Response(JSON.stringify({ requestId: 'r1' }), { status: 200 });
  });
  vi.stubGlobal('fetch', request);
  const definition: FormDefinition = { formType: 'MOE_FAS', formVersion: '2026-10', pageCount: 3, fields: [] };
  const files = [1, 2, 3].map(index => new File(['png'], `p${index}.png`, { type: 'image/png' }));
  await extractOcr(files, definition);
  expect(request.mock.calls[0][0]).toMatch(/\/api\/v1\/fas\/ocr$/);
});
