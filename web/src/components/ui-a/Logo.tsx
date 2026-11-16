import { LOGO_FILES } from './logo-files.ts';

// design.md § Logo and docs/brand/README.md: each size has its own file, which drops detail on
// purpose, so pick the one for the size and never scale another. The colours are fixed: don't
// recolour or filter it.

export type LogoProps =
  | {
      /** 140: the master (64 px and up); 64: about 40–64 px; 32: the UI; 16: favicon only. */
      size: 64 | 32 | 16;
      light?: never;
      /** Its text alternative. Default: none, for a logo beside the "spotivault" wordmark. */
      alt?: string;
      className?: string;
    }
  | {
      size: 140;
      /** The master on a light tile, for light surfaces. */
      light?: boolean;
      alt?: string;
      className?: string;
    };

/** The vinyl-vault logo, `Logo/Mark` (components.md § Brand), at one of its fixed sizes. */
export function Logo({ size, light = false, alt = '', className }: LogoProps) {
  const src = light ? LOGO_FILES.light : LOGO_FILES[size];
  return <img src={src} width={size} height={size} alt={alt} className={className} draggable={false} />;
}
