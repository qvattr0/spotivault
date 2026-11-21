// The run header's line: the same text as before ("started 01:00 · 0:42 elapsed · …"), with each
// dot drawn as its own element so it gets room around it.

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { runRunning } from '@mock/fixtures.ts';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { RunHeader } from './RunHeader.tsx';

describe('the run header', () => {
  it('spaces the dots in the run line, and keeps its text', () => {
    const { container } = render(
      <MemoryRouter>
        <LiveStoreProvider store={storeFor('running')}>
          <ToastProvider>
            <RunHeader run={runRunning} />
          </ToastProvider>
        </LiveStoreProvider>
      </MemoryRouter>,
    );
    const line = screen.getByText(
      (_, element) => element?.tagName === 'P' && /^started \d\d:\d\d · \d+:\d\d elapsed · Scheduled · stops by \d\d:\d\d/.test(element.textContent ?? ''),
    );
    expect(line.querySelectorAll('.metaDot')).toHaveLength(line.textContent!.split(' · ').length - 1);
    expect(container.querySelector('.metaDot')?.textContent).toBe('·');
  });
});
