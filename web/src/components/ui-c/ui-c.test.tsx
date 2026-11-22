import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useRef, useState } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Checkbox, TextInput } from '@/components/ui-a';
import { ChoiceCard, ChoiceCardGroup } from './ChoiceCard.tsx';
import { DetailHeader } from './DetailHeader.tsx';
import { Disclosure } from './Disclosure.tsx';
import { InsertChips } from './InsertChips.tsx';
import { OutcomePill } from './OutcomePill.tsx';
import { StatusButton } from './StatusButton.tsx';
import { useInsertAtCursor } from './use-insert-at-cursor.ts';
import { vncUrl } from './VncView.tsx';

function Choice({ onLiked = vi.fn() }: { onLiked?: (on: boolean) => void }) {
  const [value, setValue] = useState('all');
  return (
    <ChoiceCardGroup label="What to back up" value={value} onChange={setValue}>
      <ChoiceCard value="all" title="Back up all my playlists" description="Every playlist you created is tracked.">
        <Checkbox checked onChange={onLiked} label="Include Liked Songs" />
      </ChoiceCard>
      <ChoiceCard value="choose" title="I'll choose in the Library" note="Track playlists anytime." />
    </ChoiceCardGroup>
  );
}

describe('ChoiceCardGroup', () => {
  it('is a radio group: one chosen, a click on a card chooses it', async () => {
    const user = userEvent.setup();
    render(<Choice />);
    expect(screen.getByRole('radiogroup', { name: 'What to back up' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Back up all my playlists' })).toBeChecked();
    await user.click(screen.getByText('Track playlists anytime.'));
    expect(screen.getByRole('radio', { name: "I'll choose in the Library" })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Back up all my playlists' })).toHaveAccessibleDescription('Every playlist you created is tracked.');
  });

  it("lets the card's own controls work without changing the choice", async () => {
    const user = userEvent.setup();
    const onLiked = vi.fn();
    render(<Choice onLiked={onLiked} />);
    await user.click(screen.getByRole('radio', { name: "I'll choose in the Library" }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Liked Songs' }));
    expect(onLiked).toHaveBeenCalledWith(false);
    expect(screen.getByRole('radio', { name: "I'll choose in the Library" })).toBeChecked();
  });

  it('moves with the arrow keys, as a radio group does', async () => {
    const user = userEvent.setup();
    render(<Choice />);
    screen.getByRole('radio', { name: 'Back up all my playlists' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: "I'll choose in the Library" })).toBeChecked();
  });
});

describe('Disclosure', () => {
  it('opens and closes, saying so', async () => {
    const user = userEvent.setup();
    render(
      <Disclosure label="More formats" hint="FLAC, WAV">
        <p>FLAC</p>
      </Disclosure>,
    );
    const button = screen.getByRole('button', { name: /More formats/ });
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('FLAC')).not.toBeInTheDocument();
    await user.click(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByText('FLAC')).toBeInTheDocument();
  });
});

function Layout() {
  const field = useRef<HTMLInputElement>(null);
  const [pattern, setPattern] = useState('{album}/{title}');
  const insert = useInsertAtCursor(field, pattern, setPattern);
  return (
    <>
      <TextInput ref={field} aria-label="Layout" value={pattern} onChange={(e) => setPattern(e.target.value)} />
      <InsertChips items={['{track}', '{year}']} onInsert={insert} />
    </>
  );
}

describe('InsertChips', () => {
  it('types the placeholder at the cursor, and leaves the cursor after it', async () => {
    const user = userEvent.setup();
    render(<Layout />);
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: 'Layout' });
    input.focus();
    input.setSelectionRange(8, 8); // after "{album}/"
    await user.click(screen.getByRole('button', { name: 'Insert {track}' }));
    expect(input).toHaveValue('{album}/{track}{title}');
    expect(input.selectionStart).toBe(15);
    expect(input).toHaveFocus();
  });
});

describe('StatusButton, OutcomePill, DetailHeader', () => {
  it('joins a state and its action; only the action is a control', async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<StatusButton tone="green" status="OK" actionLabel="Reconnect" onAction={onAction} />);
    expect(screen.getAllByRole('button')).toHaveLength(1);
    await user.click(screen.getByRole('button', { name: 'Reconnect' }));
    expect(onAction).toHaveBeenCalledOnce();
    expect(screen.getByText('OK')).toBeInTheDocument();
  });

  it('words outcomes as web-ui.md does', () => {
    render(<OutcomePill outcome="completed_with_issues" />);
    expect(screen.getByText('Completed with issues')).toBeInTheDocument();
  });

  it('names the page after the item, with a way back', () => {
    render(
      <MemoryRouter>
        <DetailHeader backTo="/library" backLabel="Library" typeLabel="Playlist" title="Late Night Drive" meta="by you · 120 tracks" />
      </MemoryRouter>,
    );
    expect(screen.getByRole('heading', { level: 1, name: 'Late Night Drive' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Library' })).toHaveAttribute('href', '/library');
    expect(document.title).toBe('Late Night Drive · spotivault');
  });
});

describe('vncUrl', () => {
  it("is /vnc on the page's own host, secure when the page is", () => {
    expect(vncUrl({ protocol: 'http:', host: 'nas:8080' })).toBe('ws://nas:8080/vnc');
    expect(vncUrl({ protocol: 'https:', host: 'nas.lan' })).toBe('wss://nas.lan/vnc');
  });
});
