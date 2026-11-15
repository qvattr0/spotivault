import type { ReactNode } from 'react';
import styles from './WizardCard.module.css';

interface WizardCardProps {
  /** Each step's width in the drawings is its `cardWidth` in setup-steps.ts: 640 to 1300. */
  width?: number;
  children: ReactNode;
}

/** The centred card of a wizard step: bg-base, radius 12, padding 40. Each step page draws inside one. */
export function WizardCard({ width = 680, children }: WizardCardProps) {
  return (
    <div className={styles.card} style={{ width }}>
      {children}
    </div>
  );
}
