// Runs before every test file: adds Testing Library's DOM matchers (toBeInTheDocument, ...)
// and unmounts what each test rendered.
import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => cleanup());

// jsdom does no layout, so it has no scrollIntoView (Settings' SaveBar calls it). The mock's
// tests run in Node, with no DOM at all.
if (typeof Element !== 'undefined') Element.prototype.scrollIntoView ??= () => {};
