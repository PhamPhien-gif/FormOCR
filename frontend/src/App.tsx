import { useEffect, useRef, useState } from 'react';
import { extractOcr, getFormDefinition } from './api';
import type { FormDefinition, FormField, OcrResponse } from './types';

type Phase = 'idle' | 'processing' | 'review' | 'confirmed';

function validDate(value: string): boolean {
  if (!/^\d{2}\/\d{2}\/\d{4}$/.test(value)) return false;
  const [day, month, year] = value.split('/').map(Number);
  const date = new Date(year, month - 1, day);
  return year >= 1900 && date.getFullYear() === year && date.getMonth() === month - 1 && date.getDate() === day;
}

export function reviewErrors(fields: FormField[], values: Record<string, string>): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const value = (values[field.id] || '').trim();
    if (field.required && !value) errors[field.id] = 'This field is required.';
    else if (field.dataType === 'date' && value && !validDate(value)) errors[field.id] = 'Use a real date in DD/MM/YYYY format.';
  }
  return errors;
}

function groupFields(fields: FormField[]): [string, FormField[]][] {
  const sections = new Map<string, FormField[]>();
  fields.forEach(field => {
    const key = `Page ${field.page} · ${field.section}`;
    sections.set(key, [...(sections.get(key) || []), field]);
  });
  return [...sections.entries()];
}

function fileError(files: File[], pageCount: number): string | null {
  if (files.length !== 1 && files.length !== pageCount) return `Select one PDF or ${pageCount} page images in order.`;
  const pdf = files.length === 1 && /\.pdf$/i.test(files[0].name);
  const images = files.length === pageCount && files.every(file => /\.(png|jpe?g)$/i.test(file.name));
  if (!pdf && !images) return `Select one PDF or ${pageCount} PNG/JPEG images in order.`;
  if (files.reduce((sum, file) => sum + file.size, 0) > 25_000_000) return 'Files must total 25 MB or less.';
  return null;
}

export default function App() {
  const [definition, setDefinition] = useState<FormDefinition | null>(null);
  const [schemaError, setSchemaError] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<{ url: string; pdf: boolean }[]>([]);
  const [phase, setPhase] = useState<Phase>('idle');
  const [result, setResult] = useState<OcrResponse | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [message, setMessage] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const abort = new AbortController();
    getFormDefinition(abort.signal).then(setDefinition).catch(error => {
      if (error.name !== 'AbortError') setSchemaError(error.message);
    });
    return () => abort.abort();
  }, []);

  useEffect(() => {
    const next = files.map(file => ({ url: URL.createObjectURL(file), pdf: /\.pdf$/i.test(file.name) }));
    setPreviews(next);
    return () => next.forEach(item => URL.revokeObjectURL(item.url));
  }, [files]);

  useEffect(() => {
    if (phase !== 'processing') return;
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [phase]);

  function replaceFiles(nextFiles: File[]) {
    generation.current += 1;
    controller.current?.abort();
    controller.current = null;
    setFiles(nextFiles);
    setResult(null);
    setValues({});
    setErrors({});
    setMessage('');
    setElapsed(0);
    setPhase('idle');
  }

  async function process() {
    if (!definition) return;
    const invalid = fileError(files, definition.pageCount);
    if (invalid) { setMessage(invalid); return; }
    const requestId = ++generation.current;
    controller.current?.abort();
    controller.current = new AbortController();
    setMessage('');
    setElapsed(0);
    setPhase('processing');
    try {
      const response = await extractOcr(files, definition, controller.current.signal);
      if (requestId !== generation.current) return;
      if (response.formType !== definition.formType || response.formVersion !== definition.formVersion || response.requiresNewForm) {
        setMessage('This document does not match the current form template. Upload the correct form.');
        setPhase('idle');
        return;
      }
      setResult(response);
      setValues(Object.fromEntries(definition.fields.map(field => [field.id,
        response.fields[field.id]?.status === 'EXTRACTED' ? response.fields[field.id]?.value || '' : ''])));
      setPhase('review');
    } catch (error) {
      if (requestId === generation.current && (error as Error).name !== 'AbortError') {
        setMessage((error as Error).message);
        setPhase('idle');
      }
    }
  }

  function confirm() {
    if (!definition || !result) return;
    const nextErrors = reviewErrors(definition.fields, values);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) {
      setMessage('Complete the highlighted fields before confirming.');
      return;
    }
    setMessage('Review confirmed. Download the JSON file below.');
    setPhase('confirmed');
  }

  function download() {
    if (!definition || !result) return;
    const payload = {
      formType: definition.formType, formVersion: definition.formVersion,
      requestId: result.requestId, confirmedAt: new Date().toISOString(),
      values: Object.fromEntries(definition.fields.map(field => [field.id, (values[field.id] || '').trim()])),
    };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `fas-reviewed-${result.requestId}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  const extracted = result ? Object.values(result.fields).filter(field => field.status === 'EXTRACTED').length : 0;
  const sections = definition ? groupFields(definition.fields) : [];

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">F</span><span>FormOCR <small>MOE FAS</small></span></div><span className="local-badge">LOCAL OCR · CPU</span></header>
    <main>
      <div className="intro"><div><span className="eyebrow">DOCUMENT PROCESSING WORKSPACE</span><h1>Financial assistance form review</h1><p>Upload the completed form, inspect OCR suggestions, then confirm each value for export.</p></div><div className="step-list"><span className="active">01 Upload</span><span className={result ? 'active' : ''}>02 Review</span><span className={phase === 'confirmed' ? 'active' : ''}>03 Export</span></div></div>
      {schemaError && <div className="alert error" role="alert">Cannot load the form definition: {schemaError}</div>}
      <div className="workspace">
        <aside className="sidebar">
          <section className="panel"><div className="panel-heading"><span className="panel-number">01</span><div><h2>Source document</h2><p>Pages 1–3 contain the answer regions.</p></div></div>
            <input ref={uploadInput} className="visually-hidden" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" multiple onChange={event => { replaceFiles(Array.from(event.target.files || [])); event.target.value = ''; }} aria-label="Choose form files" />
            <button type="button" className="upload-zone" onClick={() => uploadInput.current?.click()}><span className="upload-icon">↑</span><strong>Choose PDF or page images</strong><span>One PDF, or three PNG/JPEG files ordered by page</span><em>MAX 25 MB TOTAL</em></button>
            {files.length > 0 && <div className="file-list">{files.map((file, index) => <div className="file-row" key={`${file.name}-${index}`}><span>{files.length === 1 ? 'PDF' : `P${index + 1}`}</span><div><strong title={file.name}>{file.name}</strong><small>{(file.size / 1024 / 1024).toFixed(2)} MB</small></div></div>)}</div>}
            {previews.length > 0 && <details className="previews"><summary>Original document preview</summary>{previews.map((item, index) => item.pdf
              ? <object key={item.url} data={item.url} type="application/pdf" aria-label="Uploaded PDF preview"><a href={item.url} target="_blank" rel="noreferrer">Open uploaded PDF</a></object>
              : <img key={item.url} src={item.url} alt={`Uploaded page ${index + 1}`} />)}</details>}
            <button className="primary-button" type="button" disabled={!definition || !files.length || phase === 'processing'} onClick={process}>{phase === 'processing' ? 'Reading form…' : result ? 'Run OCR again' : 'Process document'}</button>
            {phase === 'processing' && <p className="processing" role="status"><span className="spinner"/> Assessing image and running OCR… {elapsed}s elapsed. CPU processing can take several minutes.</p>}
            {message && <div className={`alert ${phase === 'confirmed' ? 'success' : 'error'}`} role="alert">{message}</div>}
          </section>
          <section className="panel compact"><h2>Processing notes</h2><p>OCR runs locally with RapidOCR and PP-OCRv5 English. Handwriting and signatures need human review.</p><p>For clear results, use a full-page PDF export or original camera image with all page edges visible.</p></section>
        </aside>
        <section className="review-area">
          <div className="review-header"><div><span className="eyebrow">02 · REVIEW &amp; VERIFY</span><h2>Extracted values</h2><p>{definition ? `${definition.fields.length} fields across ${definition.pageCount} pages` : 'Loading form layout…'}</p></div>{result && <div className="result-count"><strong>{extracted}</strong><span>OCR suggestions</span></div>}</div>
          {!result && <div className="empty-state"><div className="empty-glyph">▤</div><h3>Your form fields will appear here</h3><p>Choose a document and process it to see OCR suggestions. You can edit every value before export.</p></div>}
          {result && <>
            <div className={`alert ${result.requiresRecapture ? 'error' : 'info'}`}>{result.requiresRecapture ? 'Some required regions were not readable. Check the source image and fill those values manually, or upload a clearer copy.' : 'OCR suggestions are ready. Check every value against your document.'}<small>Result: {result.status} · OCR {result.ocrSeconds.toFixed(1)}s · total {result.processingSeconds.toFixed(1)}s</small></div>
            {result.issues.length > 0 && <details className="issue-list"><summary>{result.issues.length} processing notes</summary><ul>{result.issues.map((issue, index) => <li key={index}>{issue.field ? `${issue.field}: ` : ''}{issue.message}</li>)}</ul></details>}
            {Object.keys(result.transcripts).length > 0 && <details className="issue-list"><summary>Unaligned page transcripts</summary>{Object.entries(result.transcripts).map(([page, lines]) => <div key={page}><h3>Page {page}</h3><pre>{lines.join('\n')}</pre></div>)}</details>}
            {sections.map(([section, fields]) => <section className="form-section" key={section}><div className="section-title"><h3>{section}</h3><span>{fields.length} fields</span></div><div className="field-grid">{fields.map(field => {
              const suggestion = result.fields[field.id];
              return <label className="field" key={field.id}><span className="field-label">{field.label}{field.required && <b> *</b>}</span><input value={values[field.id] || ''} onChange={event => { setValues(previous => ({ ...previous, [field.id]: event.target.value })); setErrors(previous => { const next = { ...previous }; delete next[field.id]; return next; }); if (phase === 'confirmed') setPhase('review'); }} placeholder={field.dataType === 'date' ? 'DD/MM/YYYY' : 'Enter or verify value'} aria-invalid={Boolean(errors[field.id])} /><span className="field-meta">{errors[field.id] ? <em className="field-error">{errors[field.id]}</em> : suggestion?.status === 'EXTRACTED' ? <em className="suggested">OCR suggestion</em> : <em>{suggestion?.status?.replace('_', ' ').toLowerCase() || 'Manual entry'}</em>}</span></label>;
            })}</div></section>)}
            <div className="review-actions"><button className="primary-button" type="button" onClick={confirm}>{phase === 'confirmed' ? 'Confirm again' : 'Confirm reviewed values'}</button>{phase === 'confirmed' && <button className="secondary-button" type="button" onClick={download}>Download reviewed JSON ↓</button>}</div>
          </>}
        </section>
      </div>
    </main>
    <footer>FormOCR · Local document processing · No data is stored by this demo</footer>
  </div>;
}
