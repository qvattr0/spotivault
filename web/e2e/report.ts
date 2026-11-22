// Writes e2e/screenshots/index.html: every screenshot the e2e tests took, beside the drawing it
// should match, side by side or as a difference (identical pixels go black).
//
//   node e2e/report.ts      after `npm run e2e`, which also writes it at the end of its screenshots
//
// How screenshots pair with web/design-reference/ (both are 2x):
// - <node>.png, a screen: design-reference/<node>.png (screens.md gives the node ids). The S8 pages
//   are shot in each drawn frame's state (e2e/page-screens.ts), in screens.md's order.
// - E3ZmN.<node>.png, a gallery section: that section's box in the component sheet, E3ZmN.png
//   (the boxes are in src/pages/gallery/sheet.ts).
// The reference PNGs aren't committed: screens.md says how to export them.

import { closeSync, existsSync, mkdirSync, openSync, readdirSync, readSync, rmSync, writeFileSync } from 'node:fs';
import { relative } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { PAGE_SCREENS } from './page-screens.ts';
import { SHEET_NODE, SHEET_SECTIONS, SHEET_SIZE, type SheetSection } from '../src/pages/gallery/sheet.ts';

const SCREENSHOTS = fileURLToPath(new URL('./screenshots/', import.meta.url));
const REFERENCES = fileURLToPath(new URL('../design-reference/', import.meta.url));

/** Where a screenshot named `name` goes. Makes the folder if needed. */
export function screenshotPath(name: string): string {
  mkdirSync(SCREENSHOTS, { recursive: true });
  return SCREENSHOTS + name;
}

/** Deletes the screenshots whose names start with one of these, so none outlives its section. */
export function removeScreenshots(...prefixes: string[]): void {
  if (!existsSync(SCREENSHOTS)) return;
  for (const name of readdirSync(SCREENSHOTS)) {
    if (name.endsWith('.png') && prefixes.some((p) => name.startsWith(p))) rmSync(SCREENSHOTS + name);
  }
}

interface Size {
  width: number;
  height: number;
}

interface Pair {
  name: string;
  title: string;
  built: Size;
  /** The reference PNG's file name in design-reference/, and the box to show when it's the sheet. */
  reference: { file: string; size: Size; box?: SheetSection['box'] } | null;
}

/** A PNG's size in pixels, from its header. */
function pngSize(path: string): Size {
  const header = Buffer.alloc(24);
  const fd = openSync(path, 'r');
  readSync(fd, header, 0, 24, 0);
  closeSync(fd);
  return { width: header.readUInt32BE(16), height: header.readUInt32BE(20) };
}

function referenceSize(file: string): Size | null {
  return existsSync(REFERENCES + file) ? pngSize(REFERENCES + file) : null;
}

function pairFor(name: string): Pair {
  const built = pngSize(SCREENSHOTS + name);
  const node = name.replace(/\.png$/, '');

  if (node.startsWith(`${SHEET_NODE}.`)) {
    const section = SHEET_SECTIONS.find((s) => `${SHEET_NODE}.${s.node}` === node);
    const size = referenceSize(`${SHEET_NODE}.png`);
    return {
      name,
      title: `Gallery · ${section?.title ?? node}`,
      built,
      reference: section && size ? { file: `${SHEET_NODE}.png`, size, box: section.box } : null,
    };
  }

  const screen = PAGE_SCREENS.find((s) => s.node === node);
  const size = referenceSize(name);
  const scenario = screen ? (screen.step ? `"${screen.scenario}" at ${screen.step}` : `"${screen.scenario}"`) : '';
  return {
    name,
    title: screen ? `${screen.title} (${screen.path}, mock scenario ${scenario})` : node,
    built,
    reference: size ? { file: name, size } : null,
  };
}

const escape = (text: string) =>
  text.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c] ?? c);

/** A 2x PNG at its CSS size. */
function image(src: string, size: Size): string {
  return `<img src="${escape(encodeURI(src))}" width="${size.width / 2}" height="${size.height / 2}" alt="">`;
}

function drawing(pair: Pair, referencesUrl: string): string {
  const reference = pair.reference;
  if (!reference) return '<p class="none">No drawing to compare with.</p>';
  const src = referencesUrl + reference.file;
  if (!reference.box) return image(src, reference.size);
  // A box of the sheet: the sheet as a background, moved so the box shows.
  const { x, y, width, height } = reference.box;
  return `<div class="crop" style="width:${width}px;height:${height}px;background-image:url('${escape(encodeURI(src))}');background-size:${SHEET_SIZE.width}px ${SHEET_SIZE.height}px;background-position:-${x}px -${y}px"></div>`;
}

function section(pair: Pair, referencesUrl: string): string {
  const sizes = [`screenshot ${pair.built.width} × ${pair.built.height}`];
  if (pair.reference) {
    const where = pair.reference.box ? `a box of ${pair.reference.file}` : pair.reference.file;
    sizes.push(`drawing: ${where}, ${pair.reference.size.width} × ${pair.reference.size.height}`);
  }
  return `
<section id="${escape(pair.name)}">
  <h2>${escape(pair.title)} <code>${escape(pair.name)}</code></h2>
  <p class="meta">${escape(sizes.join(' · '))}</p>
  <div class="compare">
    <figure class="built"><figcaption>Built</figcaption><div class="view">${image(pair.name, pair.built)}</div></figure>
    <figure><figcaption>Drawing</figcaption><div class="view">${drawing(pair, referencesUrl)}</div></figure>
  </div>
</section>`;
}

/** Writes the report for whatever screenshots there are. Returns its path. */
export function writeReport(): string {
  mkdirSync(SCREENSHOTS, { recursive: true });
  // The sheet's sections first, then the pages' screens, then anything else by name.
  const expected = [...SHEET_SECTIONS.map((s) => `${SHEET_NODE}.${s.node}.png`), ...PAGE_SCREENS.map((s) => `${s.node}.png`)];
  const place = (name: string) => (expected.includes(name) ? expected.indexOf(name) : expected.length);
  const names = readdirSync(SCREENSHOTS)
    .filter((n) => n.endsWith('.png'))
    .sort((a, b) => place(a) - place(b) || a.localeCompare(b));
  const pairs = names.map(pairFor);
  const missing = expected.filter((n) => !names.includes(n));
  const referencesUrl = relative(SCREENSHOTS, REFERENCES).split('\\').join('/') + '/';

  const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>spotivault screenshots vs drawings</title>
<style>
  :root { color-scheme: dark; --zoom: 0.5; }
  body { margin: 0; padding: 24px 32px 64px; background: #121212; color: #fff; font: 14px/1.4 system-ui, sans-serif; }
  header { position: sticky; top: 0; z-index: 2; padding: 12px 0; background: #121212; border-bottom: 1px solid #2e2e2e; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  h2 { margin: 32px 0 4px; font-size: 16px; }
  section { scroll-margin-top: 140px; }
  code { color: #b3b3b3; font-size: 12px; }
  label { margin-right: 16px; color: #b3b3b3; }
  nav a { color: #b3b3b3; margin-right: 12px; }
  .meta, .none, .missing { color: #808080; margin: 0 0 8px; }
  .compare { display: flex; gap: 24px; align-items: flex-start; }
  figure { margin: 0; }
  figcaption { color: #808080; font-size: 12px; margin-bottom: 4px; }
  .view { zoom: var(--zoom); outline: 1px solid #2e2e2e; }
  .view img { display: block; max-width: none; }
  .crop { background-repeat: no-repeat; }
  /* Difference: the screenshot over the drawing, top-left aligned. What matches goes black. */
  body.diff .compare { display: grid; justify-items: start; }
  body.diff .compare > figure { grid-area: 1 / 1; }
  body.diff .compare > figure.built { z-index: 1; mix-blend-mode: difference; }
  body.diff figcaption { display: none; }
</style>
</head>
<body>
<header>
  <h1>Screenshots vs drawings</h1>
  <p class="meta">${pairs.length} screenshots from e2e/screenshots, ${pairs.filter((p) => p.reference).length} with a drawing in design-reference. Written ${escape(new Date().toISOString())}.</p>
  <label><input type="radio" name="mode" value="side" checked> Side by side</label>
  <label><input type="radio" name="mode" value="diff"> Difference</label>
  <label>Zoom <input id="zoom" type="range" min="0.2" max="1" step="0.05" value="0.5"> <span id="zoom-value">50 %</span></label>
  <nav>${pairs.map((p) => `<a href="#${escape(p.name)}">${escape(p.name.replace(/\.png$/, ''))}</a>`).join('')}</nav>
</header>
${missing.length ? `<p class="missing">Not captured: ${escape(missing.join(', '))}.</p>` : ''}
${pairs.map((p) => section(p, referencesUrl)).join('\n')}
<script>
  for (const radio of document.querySelectorAll('input[name=mode]')) {
    radio.addEventListener('change', () => document.body.classList.toggle('diff', radio.value === 'diff' && radio.checked));
  }
  const zoom = document.getElementById('zoom');
  zoom.addEventListener('input', () => {
    document.documentElement.style.setProperty('--zoom', zoom.value);
    document.getElementById('zoom-value').textContent = Math.round(zoom.value * 100) + ' %';
  });
</script>
</body>
</html>
`;
  const path = SCREENSHOTS + 'index.html';
  writeFileSync(path, html);
  return path;
}

// Run as a script: node e2e/report.ts
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const path = writeReport();
  console.log(`report: ${path}`);
}
