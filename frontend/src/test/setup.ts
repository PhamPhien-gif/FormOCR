import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

URL.createObjectURL = vi.fn(() => 'blob:test-preview');
URL.revokeObjectURL = vi.fn();
