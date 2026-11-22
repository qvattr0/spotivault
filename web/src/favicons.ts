// The favicons, straight from the brand files (docs/brand/README.md): logo-32, and logo-16 for
// 16 px. Added from code rather than index.html so the dev server can serve them too.

import logo16 from '@brand/logo-16.svg?url';
import logo32 from '@brand/logo-32.svg?url';

export function addFavicons(): void {
  for (const [href, size] of [
    [logo32, '32x32'],
    [logo16, '16x16'],
  ] as const) {
    const link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    link.sizes = size;
    link.href = href;
    document.head.append(link);
  }
}
