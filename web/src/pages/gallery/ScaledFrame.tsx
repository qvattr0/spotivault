import { useEffect, useRef, useState, type ReactNode } from 'react';
import styles from './LiveShell.module.css';

interface Props {
  /** The size the children are laid out at, in CSS px: a drawing's 1440 × 960. */
  width: number;
  height: number;
  children: ReactNode;
}

/** Lays its children out at a fixed size, then scales them down to fit the width it's given. */
export function ScaledFrame({ width, height, children }: Props) {
  const outer = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);

  useEffect(() => {
    const element = outer.current;
    // jsdom (the unit tests) has no ResizeObserver: draw at full size there.
    if (!element || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => setScale(Math.min(1, element.clientWidth / width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [width]);

  return (
    <div ref={outer} className={styles.fit} style={{ height: height * scale }}>
      <div className={styles.scaled} style={{ width, height, transform: `scale(${scale})` }}>
        {children}
      </div>
    </div>
  );
}
