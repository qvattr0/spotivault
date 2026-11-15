import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { sections as uiA } from '@/components/ui-a/gallery.tsx';
import { sections as uiB } from '@/components/ui-b/gallery.tsx';
import { leadSections as shellLead, sections as shell } from '@/shell/gallery.tsx';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { arrangeSections } from './arrange.ts';
import { foundations } from './foundations.tsx';
import { GalleryPage } from './GalleryPage.tsx';
import { SheetSection } from './SheetSection.tsx';


const ALL = arrangeSections([foundations, ...shellLead, ...uiA, ...uiB, ...shell]);

function renderGallery(path = '/gallery') {
  const router = createMemoryRouter([{ path: '/gallery', element: <GalleryPage /> }], { initialEntries: [path] });
  render(
    <LiveStoreProvider store={storeFor('running')}>
      <RouterProvider router={router} />
    </LiveStoreProvider>,
  );
  return router;
}

/** Answers the mock's /__mock/scenario like the mock does, or 404 like a real controller. */
function stubMock(present: boolean) {
  const fetch = vi.fn(async (_url: string, init?: RequestInit) => {
    if (!present) return new Response('Not found', { status: 404 });
    const body = init?.method === 'POST' ? init.body : JSON.stringify({ scenario: 'idle' });
    return new Response(body as string, { status: 200, headers: { 'Content-Type': 'application/json' } });
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe('GalleryPage', () => {
  it("shows every group's sections, each entry under its spec label", () => {
    renderGallery();
    for (const section of ALL) {
      const region = screen.getByRole('region', { name: section.title });
      for (const entry of section.entries) {
        expect(within(region).getByText(entry.title, { selector: 'figcaption' })).toBeInTheDocument();
      }
    }
    expect(screen.getByRole('link', { name: 'Shell, live' })).toHaveAttribute('href', '/gallery?view=shell');
  });

  it('has a unique anchor for every section and entry', () => {
    const ids = ALL.flatMap((s) => [s.id, ...s.entries.map((e) => e.id)]);
    const repeated = ids.filter((id, i) => ids.indexOf(id) !== i);
    expect(repeated, `ids used twice: ${repeated.join(', ')}`).toEqual([]);
  });

  it('shows an entry that throws as an error in its place, and draws the rest', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <SheetSection
        section={{
          id: 'controls',
          title: 'Controls',
          entries: [
            { id: 'broken', title: 'Button/Broken', render: () => { throw new Error('no props'); } },
            { id: 'fine', title: 'Button/Fine', render: () => <button type="button">Run now</button> },
          ],
        }}
      />,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('Button/Broken failed to draw: no props');
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });
});

describe('the live shell view', () => {
  it('turns its controls off when no mock backend answers', async () => {
    stubMock(false);
    renderGallery('/gallery?view=shell');
    expect(await screen.findByText(/No mock backend answers/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run now' })).toBeDisabled();
    expect(screen.getByTitle('Live shell')).toHaveAttribute('src', '/dashboard');
  });

  it("starts the mock in a drawing's scenario and opens its route", async () => {
    const fetch = stubMock(true);
    const router = renderGallery('/gallery?view=shell');
    const paused = await screen.findByRole('button', { name: /Dashboard · Paused/ });
    await vi.waitFor(() => expect(paused).toBeEnabled());

    const player = screen.getByRole('button', { name: /Player · View-only/ });
    await userEvent.click(player);

    expect(fetch).toHaveBeenCalledWith('/__mock/scenario', expect.objectContaining({ method: 'POST', body: '{"scenario":"running"}' }));
    expect(await screen.findByRole('status')).toHaveTextContent('Player · View-only (during a run): sent.');
    expect(player).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTitle('Live shell')).toHaveAttribute('src', '/player');
    expect(router.state.location.search).toBe('?view=shell&screen=jh5YJ');
  });

  it("shows this page's own live run state", () => {
    stubMock(false);
    renderGallery('/gallery?view=shell');
    expect(screen.getByTestId('gallery-run-state')).toHaveAttribute('data-run-state', 'running');
  });
});
