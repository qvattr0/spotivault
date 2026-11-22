import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MAX_TOASTS, TOAST_DURATION_MS } from './toast-context.ts';
import { ToastProvider } from './ToastProvider.tsx';
import { ToastViewport } from './ToastViewport.tsx';
import { useToast } from './use-toast.ts';

/** A button that shows the given toasts, as a page would on "Back up now". */
function ShowButton({ messages }: { messages: string[] }) {
  const toast = useToast();
  return (
    <button type="button" onClick={() => messages.forEach((message) => toast.show(message))}>
      Show
    </button>
  );
}

function renderWithToasts(...messages: string[]) {
  render(
    <ToastProvider>
      <ShowButton messages={messages} />
      <ToastViewport />
    </ToastProvider>,
  );
  return () => fireEvent.click(screen.getByRole('button', { name: 'Show' }));
}

describe('toasts', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('appear in a live region that is there before them, so they are announced', () => {
    const show = renderWithToasts('Added to the current run');
    const region = screen.getByRole('status');
    expect(region).toHaveAttribute('aria-live', 'polite');
    expect(region).toBeEmptyDOMElement();

    show();
    expect(region).toHaveTextContent('Added to the current run');
  });

  it('go away on their own', () => {
    const show = renderWithToasts('Cover saved · 3000 × 2000');
    show();
    act(() => {
      vi.advanceTimersByTime(TOAST_DURATION_MS - 1);
    });
    expect(screen.getByText('Cover saved · 3000 × 2000')).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.queryByText('Cover saved · 3000 × 2000')).not.toBeInTheDocument();
  });

  it(`show at most ${MAX_TOASTS} at once, dropping the oldest`, () => {
    const messages = Array.from({ length: MAX_TOASTS + 1 }, (_, i) => `Toast ${i + 1}`);
    const show = renderWithToasts(...messages);
    show();
    expect(screen.queryByText('Toast 1')).not.toBeInTheDocument();
    expect(screen.getByText(`Toast ${MAX_TOASTS + 1}`)).toBeInTheDocument();
  });

  it('need a provider', () => {
    const quiet = vi.spyOn(console, 'error').mockImplementation(() => {});
    expect(() => render(<ShowButton messages={[]} />)).toThrow(/ToastProvider/);
    quiet.mockRestore();
  });
});
