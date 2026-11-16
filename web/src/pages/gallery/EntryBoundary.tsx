import { Component, type ReactNode } from 'react';
import styles from './GalleryPage.module.css';

interface Props {
  /** The entry's title, to say which one broke. */
  title: string;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Shows an entry's error in its place instead of blanking the whole gallery, while the groups are
 * still being built. React offers this only as a class component (an "error boundary").
 * The e2e tests fail on any `data-gallery-error` and name the entry.
 */
export class EntryBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <p role="alert" className={styles.entryError} data-gallery-error={this.props.title}>
        {this.props.title} failed to draw: {error.message}
      </p>
    );
  }
}
