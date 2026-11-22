// Settings › Container (web-ui.md § Container), and plan D11's warning: M1 doesn't enforce
// UI_PASSWORD, so when it's set the section says so, without the password.

import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { container } from '@mock/fixtures.ts';
import { ContainerSection } from './ContainerSection.tsx';

function section() {
  return screen.getByRole('region', { name: 'Container' });
}

describe('ContainerSection', () => {
  it('shows the environment, and no warning while UI_PASSWORD is unset', () => {
    render(<ContainerSection container={container} />);
    expect(within(section()).getByText('spotivault')).toBeInTheDocument();
    expect(within(section()).getByText('/music → /Music')).toBeInTheDocument();
    expect(within(section()).queryByText(/UI_PASSWORD/)).not.toBeInTheDocument();
    expect(within(section()).queryByRole('status')).not.toBeInTheDocument();
  });

  it("warns when UI_PASSWORD is set: it isn't asked for in this version", () => {
    render(<ContainerSection container={{ ...container, ui_password_env_set: true }} />);
    const warning = within(section()).getByRole('status');
    expect(warning).toHaveTextContent("UI_PASSWORD is set, but this version doesn't ask for a password yet.");
    expect(warning).toHaveTextContent('Anyone on your network can open this page, so keep spotivault off the internet.');
  });
});
