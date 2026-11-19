import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { SearchInput } from './SearchInput.tsx';
import { Select } from './Select.tsx';
import { TextInput } from './TextInput.tsx';

describe('TextInput', () => {
  it('is named by its label and described by its hint', () => {
    render(<TextInput label="Client ID" hint="From your app's page." placeholder="Paste your Client ID" />);
    const input = screen.getByRole('textbox', { name: 'Client ID' });
    expect(input).toHaveAccessibleDescription("From your app's page.");
    expect(input).not.toHaveAttribute('aria-invalid');
  });

  it('shows an error in place of the hint, and is invalid', () => {
    render(<TextInput label="Client ID" hint="From your app's page." error="That isn't a Client ID." />);
    const input = screen.getByRole('textbox', { name: 'Client ID' });
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(input).toHaveAccessibleDescription("That isn't a Client ID.");
    expect(screen.queryByText("From your app's page.")).not.toBeInTheDocument();
  });

  it('takes typing', async () => {
    const onChange = vi.fn();
    render(<TextInput aria-label="Webhook URL" onChange={onChange} />);
    await userEvent.type(screen.getByRole('textbox', { name: 'Webhook URL' }), 'abc');
    expect(onChange).toHaveBeenCalledTimes(3);
  });

  it('shows a fixed prefix and suffix around the value', () => {
    render(<TextInput aria-label="Layout" prefix="Music/" suffix=".m4a" defaultValue="{title}" />);
    expect(screen.getByText('Music/')).toBeInTheDocument();
    expect(screen.getByText('.m4a')).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Layout' })).toHaveValue('{title}');
  });
});

function Search({ onClear }: { onClear?: () => void }) {
  const [q, setQ] = useState('');
  return (
    <SearchInput
      placeholder="Search in Library"
      value={q}
      onChange={(event) => setQ(event.target.value)}
      onClear={() => {
        setQ('');
        onClear?.();
      }}
    />
  );
}

describe('SearchInput', () => {
  it('is a search box named by its placeholder', () => {
    render(<SearchInput placeholder="Search in Library" />);
    expect(screen.getByRole('searchbox', { name: 'Search in Library' })).toBeInTheDocument();
  });

  it('shows a clear button only while there is text', async () => {
    const onClear = vi.fn();
    render(<Search onClear={onClear} />);
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
    await userEvent.type(screen.getByRole('searchbox'), 'indie');
    await userEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(onClear).toHaveBeenCalledOnce();
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
  });

  it('clears on Escape', async () => {
    const onClear = vi.fn();
    render(<Search onClear={onClear} />);
    await userEvent.type(screen.getByRole('searchbox'), 'indie{Escape}');
    expect(onClear).toHaveBeenCalledOnce();
    expect(screen.getByRole('searchbox')).toHaveValue('');
  });
});

describe('Select', () => {
  const SORTS = [
    { value: 'backed-up', label: 'Recently backed up' },
    { value: 'name', label: 'Name' },
  ];

  it('is a native select named by its label, showing the current choice', () => {
    render(<Select label="Sort" options={SORTS} value="backed-up" onChange={() => {}} />);
    expect(screen.getByRole('combobox', { name: 'Sort' })).toHaveValue('backed-up');
    expect(screen.getByText('Recently backed up', { selector: 'span' })).toBeInTheDocument();
  });

  it('reports the chosen value', async () => {
    const onChange = vi.fn();
    render(<Select label="Sort" options={SORTS} value="backed-up" onChange={onChange} />);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Sort' }), 'Name');
    expect(onChange).toHaveBeenCalledWith('name');
  });

  it('shows a prefix before the choice', () => {
    render(
      <Select
        label="Run"
        variant="boxed"
        prefix="Run:"
        options={[{ value: 'all', label: 'All' }]}
        value="all"
        onChange={() => {}}
      />,
    );
    expect(screen.getByText('Run: All')).toBeInTheDocument();
  });
});
