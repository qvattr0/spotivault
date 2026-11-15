import type { ReactNode } from 'react';

// The shape every component group exports for the gallery (src/components/*/gallery.tsx,
// src/shell/gallery.tsx).

export interface GalleryEntry {
  /** Anchor id, kebab-case and unique on the page: 'button-primary'. */
  id: string;
  /** The component's name as in components.md: 'Button/Primary'. */
  title: string;
  /** The .pen node id from components.md, to compare with the reference sheet: 'vcJS5'. */
  node?: string;
  /** Draws every state and variant side by side. */
  render: () => ReactNode;
  /**
   * Starts a new line and keeps it to itself, as the list rows and the now-playing strip do on the
   * sheet. Without it, entries sit side by side and wrap.
   */
  ownRow?: boolean;
}

export interface GallerySection {
  /** Anchor id: 'controls'. */
  id: string;
  /**
   * As on the component sheet: 'Controls'. A part of a sheet section can say which:
   * 'Feedback · Status pill'. The gallery shows sections of the same sheet section, or of the same
   * title, as one (arrange.ts).
   */
  title: string;
  /**
   * The .pen node id of a section that isn't on the sheet. Sheet sections take the sheet's
   * (sheet.ts), which names their screenshots.
   */
  node?: string;
  entries: GalleryEntry[];
}
