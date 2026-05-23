# NewBro Walkie — Frontend Handoff

Working React frontend split into HTML / CSS / JSX files. Uses React + Babel via CDN
so it runs as-is without a build step. Open `index.html` in a browser (or serve the
folder with any static file server).

## Files

- `index.html`   – Shell, loads scripts and styles
- `styles.css`   – Design tokens (CSS variables), keyframes, base reset
- `app.jsx`      – Main React app (channels, wheel, views, CTA)
- `characters.jsx` – Hand-drawn (简笔画) character SVGs: cat, rabbit, fox, person

## Running locally

```
# any static server works, e.g.
python3 -m http.server 8000
# then open http://localhost:8000
```

> Note: opening `index.html` directly with `file://` will fail to load the
> `.jsx` scripts in some browsers. Use a static server.

## Production build

For production, swap Babel-in-browser for a real build pipeline (Vite, Next,
etc.). The component code is plain React — drop `app.jsx` + `characters.jsx`
into your build, rename to `.jsx` modules, and replace the global `React.*`
calls with `import { useState, useEffect, useRef } from 'react'`.

## Design tokens

All colors and fonts live in `:root` in `styles.css`. To change the accent,
edit `--coral` (and optionally `--coral-soft`).
