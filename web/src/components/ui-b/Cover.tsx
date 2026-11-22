import { useState } from 'react';
import { Disc3, Heart, Music } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './Cover.module.css';

export type CoverKind = 'playlist' | 'liked' | 'album';

export interface CoverProps {
  /** The image URL (`/api/library/{id}/cover`, `/api/albums/{id}/cover`), or null when there is none. */
  src?: string | null;
  /** Liked Songs always shows its tile, whatever `src` is (web-ui.md § Detail view). */
  kind?: CoverKind;
  /** Width and height in px (44 in rows, 52 in the now-playing strip), or 'fill' for a card's art. */
  size: number | 'fill';
  className?: string;
}

/**
 * Cover art. With no image, or one that fails to load, it shows a placeholder tile with a glyph:
 * `music` for playlists, `disc-3` for albums (components.md § Card), the heart tile for Liked Songs.
 * Covers sit next to the item's name, so they're decorative (empty alt).
 */
export function Cover({ src, kind = 'playlist', size, className }: CoverProps) {
  // Remember which URL failed, so a new URL gets a fresh try without an effect.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const showImage = kind !== 'liked' && src && src !== failedSrc;
  const large = size === 'fill' || size > 64;
  const box = size === 'fill' ? undefined : { width: size, height: size };

  const Glyph = kind === 'liked' ? Heart : kind === 'album' ? Disc3 : Music;

  return (
    <div
      className={cx(
        styles.cover,
        size === 'fill' && styles.fill,
        large && styles.large,
        kind === 'liked' && styles.liked,
        className,
      )}
      style={box}
    >
      {showImage ? (
        <img className={styles.image} src={src} alt="" onError={() => setFailedSrc(src)} />
      ) : (
        <Glyph className={styles.glyph} size={large ? 40 : 18} aria-hidden />
      )}
    </div>
  );
}
