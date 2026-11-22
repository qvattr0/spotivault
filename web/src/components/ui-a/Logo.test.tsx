import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import logo16 from '@brand/logo-16.svg?url';
import logo32 from '@brand/logo-32.svg?url';
import logo64 from '@brand/logo-64.svg?url';
import logoLight from '@brand/logo-light.svg?url';
import logo140 from '@brand/logo.svg?url';
import { Brand } from './Brand.tsx';
import { Logo } from './Logo.tsx';

// Vite inlines small SVGs as data: URLs, so compare with the brand files' own URLs.
const NAMES = new Map([
  [logo140, 'logo.svg'],
  [logo64, 'logo-64.svg'],
  [logo32, 'logo-32.svg'],
  [logo16, 'logo-16.svg'],
  [logoLight, 'logo-light.svg'],
]);

/** The brand file an <img> shows, by name. */
function file(img: Element | null) {
  return NAMES.get(img?.getAttribute('src') ?? '');
}

describe('Logo', () => {
  it('uses the brand file made for its size, at that size', () => {
    const { container } = render(<Logo size={32} />);
    const img = container.querySelector('img');
    expect(file(img)).toBe('logo-32.svg');
    expect(img).toHaveAttribute('width', '32');
    expect(img).toHaveAttribute('height', '32');
    // Beside the wordmark it's decorative.
    expect(img).toHaveAttribute('alt', '');
  });

  it('picks the file made for each size, never scaling another', () => {
    const { container } = render(
      <>
        <Logo size={140} />
        <Logo size={64} />
        <Logo size={16} />
      </>,
    );
    const imgs = [...container.querySelectorAll('img')];
    expect(imgs.map((img) => [file(img), img.getAttribute('width')])).toEqual([
      ['logo.svg', '140'],
      ['logo-64.svg', '64'],
      ['logo-16.svg', '16'],
    ]);
  });

  it('has a light master for light surfaces', () => {
    render(<Logo size={140} light alt="spotivault" />);
    expect(file(screen.getByRole('img', { name: 'spotivault' }))).toBe('logo-light.svg');
  });
});

describe('Brand', () => {
  it('shows the wordmark for the sidebar and the wizard', () => {
    render(
      <>
        <Brand variant="sidebar" />
        <Brand variant="wizard" />
      </>,
    );
    expect(screen.getByText('spotivault')).toBeInTheDocument();
    expect(screen.getByText('spotivault setup')).toBeInTheDocument();
  });
});
