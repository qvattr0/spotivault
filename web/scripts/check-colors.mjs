#!/usr/bin/env node
// Fails if a colour value is typed into src/ outside the two files allowed to hold them:
// - src/design/tokens.css, generated from the .pen variables (use var(--accent) and friends);
// - src/styles/fixed.css, the fixed colours the drawings type in (components.md § Effects).
// The logo SVGs in docs/brand keep their own fixed colours and aren't checked.
//
//   node scripts/check-colors.mjs     (npm run check:colors)

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = fileURLToPath(new URL('..', import.meta.url));
const src = join(web, 'src');
const ALLOWED = new Set(['src/design/tokens.css', 'src/styles/fixed.css', 'src/api/schema.ts']);
const CHECKED = /\.(css|ts|tsx)$/;
// #RGB, #RGBA, #RRGGBB, #RRGGBBAA, and the colour functions.
const COLOUR = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b|\b(?:rgba?|hsla?|oklch|oklab|lab|lch)\(/g;

function* files(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (CHECKED.test(name)) yield path;
  }
}

const problems = [];
for (const path of files(src)) {
  const rel = relative(web, path).split('\\').join('/');
  if (ALLOWED.has(rel)) continue;
  readFileSync(path, 'utf8')
    .split('\n')
    .forEach((line, i) => {
      for (const match of line.matchAll(COLOUR)) problems.push(`${rel}:${i + 1}: ${match[0]}`);
    });
}

if (problems.length) {
  console.error('check-colors: colour values outside tokens.css and fixed.css. Use a var(--token) instead:');
  for (const p of problems) console.error(`  ${p}`);
  process.exit(1);
}
console.log('check-colors: no stray colour values in src/.');
