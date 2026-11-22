// Every global stylesheet, in order. main.tsx imports this once.
// Fonts are self-hosted from the @fontsource packages: the app runs on a LAN and loads nothing
// from the internet. Figtree in the weights the design uses (400 to 800), JetBrains Mono for
// logs and paths.

import '@fontsource/figtree/400.css';
import '@fontsource/figtree/500.css';
import '@fontsource/figtree/600.css';
import '@fontsource/figtree/700.css';
import '@fontsource/figtree/800.css';
import '@fontsource/jetbrains-mono/400.css';

import '../design/tokens.css';
import './fixed.css';
import './base.css';
