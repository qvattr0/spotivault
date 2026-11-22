import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Checkbox } from './Checkbox.tsx';
import { Chip } from './Chip.tsx';
import { ChipGroup } from './ChipGroup.tsx';
import { ChipLink } from './ChipLink.tsx';
import { Toggle } from './Toggle.tsx';
import { ViewSwitch, type ViewMode } from './ViewSwitch.tsx';
import { WeekCell } from './WeekCell.tsx';

describe('Toggle', () => {
  it('is a switch that reports the flipped value', async () => {
    const onChange = vi.fn();
    render(<Toggle checked={false} onChange={onChange} label="Track Late Night Drive" />);
    const toggle = screen.getByRole('switch', { name: 'Track Late Night Drive' });
    expect(toggle).not.toBeChecked();
    await userEvent.click(toggle);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('flips with Space from the keyboard', async () => {
    const onChange = vi.fn();
    render(<Toggle checked onChange={onChange} label="Write .m3u playlists" />);
    await userEvent.tab();
    await userEvent.keyboard(' ');
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('does nothing when disabled', async () => {
    const onChange = vi.fn();
    render(<Toggle checked onChange={onChange} label="Demo" disabled />);
    await userEvent.click(screen.getByRole('switch'));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('Checkbox', () => {
  it('toggles from a click on its label', async () => {
    const onChange = vi.fn();
    render(<Checkbox checked={false} onChange={onChange} label="I understand" />);
    expect(screen.getByRole('checkbox', { name: 'I understand' })).not.toBeChecked();
    await userEvent.click(screen.getByText('I understand'));
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('works without a visible label', async () => {
    const onChange = vi.fn();
    render(<Checkbox checked onChange={onChange} aria-label="Run finished with issues: webhook" />);
    const box = screen.getByRole('checkbox', { name: 'Run finished with issues: webhook' });
    expect(box).toBeChecked();
    await userEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(false);
  });

  it('does nothing when disabled', async () => {
    const onChange = vi.fn();
    render(<Checkbox checked={false} onChange={onChange} label="Confirm" disabled />);
    await userEvent.click(screen.getByText('Confirm'));
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('Chip', () => {
  it('is a toggle button', () => {
    render(
      <>
        <Chip selected>Spytify</Chip>
        <Chip selected={false}>Controller</Chip>
      </>,
    );
    expect(screen.getByRole('button', { name: 'Spytify' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Controller' })).toHaveAttribute('aria-pressed', 'false');
  });
});

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'tracked', label: 'Tracked' },
  { value: 'untracked', label: 'Not tracked' },
];

function Filters({ onChange }: { onChange?: (value: string) => void }) {
  const [value, setValue] = useState('all');
  return (
    <ChipGroup
      label="Filter"
      options={FILTERS}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange?.(next);
      }}
    />
  );
}

describe('ChipGroup', () => {
  it('is a radio group with one chip on', () => {
    render(<Filters />);
    expect(screen.getByRole('radiogroup', { name: 'Filter' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'All' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Tracked' })).not.toBeChecked();
  });

  it('is one Tab stop: only the chosen chip', async () => {
    render(<Filters />);
    await userEvent.tab();
    expect(screen.getByRole('radio', { name: 'All' })).toHaveFocus();
    expect(screen.getByRole('radio', { name: 'Tracked' })).toHaveAttribute('tabindex', '-1');
  });

  it('chooses with a click', async () => {
    const onChange = vi.fn();
    render(<Filters onChange={onChange} />);
    await userEvent.click(screen.getByRole('radio', { name: 'Not tracked' }));
    expect(onChange).toHaveBeenCalledWith('untracked');
    expect(screen.getByRole('radio', { name: 'Not tracked' })).toBeChecked();
  });

  it('moves and chooses with the arrow keys, wrapping', async () => {
    const onChange = vi.fn();
    render(<Filters onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Tracked' })).toHaveFocus();
    expect(screen.getByRole('radio', { name: 'Tracked' })).toBeChecked();
    await userEvent.keyboard('{End}');
    expect(screen.getByRole('radio', { name: 'Not tracked' })).toBeChecked();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'All' })).toHaveFocus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(screen.getByRole('radio', { name: 'Not tracked' })).toHaveFocus();
    expect(onChange.mock.calls.map(([value]) => value)).toEqual(['tracked', 'untracked', 'all', 'untracked']);
  });
});

describe('ChipLink', () => {
  it('marks the open page', () => {
    render(
      <MemoryRouter initialEntries={['/history/runs']}>
        <ChipLink to="/history/runs">Runs</ChipLink>
        <ChipLink to="/history/tracks">Tracks</ChipLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Runs' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Tracks' })).not.toHaveAttribute('aria-current');
  });
});

function View({ onChange }: { onChange: (value: ViewMode) => void }) {
  const [view, setView] = useState<ViewMode>('list');
  return (
    <ViewSwitch
      value={view}
      onChange={(next) => {
        setView(next);
        onChange(next);
      }}
    />
  );
}

describe('ViewSwitch', () => {
  it('names its icon-only segments', () => {
    render(<View onChange={() => {}} />);
    expect(screen.getByRole('radiogroup', { name: 'View' })).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'List' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Grid' })).not.toBeChecked();
  });

  it('switches by click and by arrow key', async () => {
    const onChange = vi.fn();
    render(<View onChange={onChange} />);
    await userEvent.click(screen.getByRole('radio', { name: 'Grid' }));
    expect(onChange).toHaveBeenLastCalledWith('grid');
    await userEvent.keyboard('{ArrowLeft}');
    expect(onChange).toHaveBeenLastCalledWith('list');
    expect(screen.getByRole('radio', { name: 'List' })).toHaveFocus();
  });
});

describe('WeekCell', () => {
  it('is a toggle button named by its hour', async () => {
    const onClick = vi.fn();
    render(<WeekCell active={false} label="Tue 02:00–03:00" onClick={onClick} />);
    const cell = screen.getByRole('button', { name: 'Tue 02:00–03:00' });
    expect(cell).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(cell);
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('read-only, is not a control', () => {
    render(<WeekCell readOnly active label="Mon 01:00–02:00" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
