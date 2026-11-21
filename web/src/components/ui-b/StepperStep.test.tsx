import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StepperStep } from './StepperStep.tsx';

describe('StepperStep', () => {
  it('tells screen readers a step is done', () => {
    render(<StepperStep state="done" label="Welcome" />);
    expect(screen.getByText('Welcome')).toHaveTextContent('Welcome, done');
  });

  it('shows a tick only when done', () => {
    const { container, rerender } = render(<StepperStep state="done" label="Log in" />);
    expect(container.querySelector('svg')).not.toBeNull();
    rerender(<StepperStep state="active" label="Log in" />);
    expect(container.querySelector('svg')).toBeNull();
    expect(screen.getByText('Log in')).toHaveTextContent(/^Log in$/);
  });

  it('marks an animation for the CSS, with its delay, and nothing for a screen reader', () => {
    const { container, rerender } = render(<StepperStep state="done" label="Log in" anim="done-from-active" animDelay={400} />);
    const step = container.firstElementChild as HTMLElement;
    expect(step).toHaveAttribute('data-anim', 'done-from-active');
    expect(step.style.getPropertyValue('--anim-delay')).toBe('400ms');
    expect(screen.getByText('Log in')).toHaveTextContent(/^Log in, done$/);
    rerender(<StepperStep state="done" label="Log in" />);
    expect(step).not.toHaveAttribute('data-anim');
    expect(step.style.getPropertyValue('--anim-delay')).toBe('');
  });

  it('draws each state', () => {
    const { container, rerender } = render(<StepperStep state="todo" label="Log in" />);
    expect(container.firstElementChild).toHaveClass('todo');
    rerender(<StepperStep state="active" label="Log in" />);
    expect(container.firstElementChild).toHaveClass('active');
  });
});
