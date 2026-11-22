import type { Setup } from '@/api';
import { Brand, Logo } from '@/components/ui-a';
import { WizardStepper } from './WizardStepper.tsx';
import styles from './WizardTop.module.css';

interface WizardTopProps {
  /** The setup state, for the stepper. Null leaves the stepper out (the Reconnect flow). */
  setup: Setup | null;
  /** The slug of the step on screen. */
  current: string | undefined;
  /** In place of "spotivault setup" (the Reconnect flow). */
  title?: string;
}

/** The top of every wizard screen: Logo/Mark 32 and "spotivault setup", then the stepper 28 below (components.md § Stepper). */
export function WizardTop({ setup, current, title }: WizardTopProps) {
  return (
    <header className={styles.top}>
      {title ? (
        <span className={styles.brand}>
          <Logo size={32} />
          <span className={styles.title}>{title}</span>
        </span>
      ) : (
        <Brand variant="wizard" />
      )}
      {setup && (
        // The stepper is 1016 wide: narrower windows scroll it sideways.
        <div className={styles.stepper}>
          <WizardStepper setup={setup} current={current} />
        </div>
      )}
    </header>
  );
}
