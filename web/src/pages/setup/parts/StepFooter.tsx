import type { ReactNode } from 'react';
import { ButtonLink } from '@/components/ui-a';
import styles from './Step.module.css';

interface StepFooterProps {
  /** Where Back goes. Left out: no Back (step 1). */
  back?: string;
  /** In place of the Back link: a Back button that does something else (the Reconnect flow). */
  start?: ReactNode;
  /** Grey text left of the buttons: why Continue waits ("Gapless playback needs to be off"). */
  hint?: ReactNode;
  /** The buttons at the right: Continue, Retry. */
  children?: ReactNode;
}

/** The foot of a wizard step: Back at the left, the hint and Continue at the right (h2Qgw, wNpTP). */
export function StepFooter({ back, start, hint, children }: StepFooterProps) {
  return (
    <div className={styles.footer}>
      {back ? (
        <ButtonLink variant="tertiary" to={back}>
          Back
        </ButtonLink>
      ) : (
        start
      )}
      <div className={styles.footerEnd}>
        {hint ? (
          <p className={styles.hint} role="status">
            {hint}
          </p>
        ) : null}
        {children}
      </div>
    </div>
  );
}
