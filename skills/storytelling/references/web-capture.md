# From web artwork to publishable media

Use code-native canvas/SVG/HTML for exact diagrams, layout and motion. Use image generation for illustration, textures or scene changes when useful; inspect an existing image before editing it. Use the host's available image tool, keep the prompt and selected output, and do not pretend an optional external provider is configured.

`capture_web.mjs` uses an isolated headless Playwright browser for local artwork. It does not touch a logged-in browser or creator account. Dependencies are optional: Node.js, Playwright/Chromium, and FFmpeg for moving exports. In a full repository checkout run `npm install`; in a standalone skill folder run `npm install --no-save playwright`. Then run `npx playwright install chromium`, or supply `--browser` for an existing Chromium executable. The `--browser` option replaces only the browser download; the Playwright package is still required. The script blocks network resources; use local fonts, images and libraries.

## Static article and long-image slices

```bash
node scripts/capture_web.mjs --input /path/article.html --output /tmp/article-long --width 1080 --height 1440
node scripts/capture_web.mjs --input /path/article.html --output /tmp/article-slices --mode slices --width 1080 --slice-height 1600
```

A full screenshot preserves a design for review; ordered slices plus GIFs preserve a long reading experience inside an editor. Select slice boundaries intentionally around headings/figures in production; automatic equal-height slices are only a starting export and may split text. Keep readable text outside the image when search/accessibility or platform editing matters.

## Deterministic motion

Author `window.renderFrame(seconds)` so every state is a pure function of time (or is reset to a known state before seeking). Use seeded noise and explicit cameras. A Three.js scene can render its camera, uniforms and particles in that function; a GSAP timeline can seek to the supplied time. Do not rely on wall-clock animation, scroll-triggered playback or unseeded physics.

```bash
node scripts/capture_web.mjs --input templates/motion-scene.html --output /tmp/motion --mode video --width 1280 --height 720 --seconds 6 --fps 24
node scripts/capture_web.mjs --input templates/motion-scene.html --output /tmp/motion-gif --mode gif --width 640 --height 360 --seconds 3 --fps 12
```

The included Canvas scene is a real reusable concept animation: particles converge, an observation/connection/understanding chain appears, and a title enters. Edit its configuration and geometry for the story. It is not tracking, simulation evidence or Gaussian reconstruction. MP4/GIF exports are silent; mix narration and music separately. GIF has no audio. Test a short low-resolution export before a long render.

For overlays on actual footage, choose screen-space tracking or calibrated scene coordinates, use alpha or explicit compositing, and match timing/occlusion. A full-frame generated scene cannot stand in for a tracked overlay. See the cinematic/video guides for method selection and fidelity checks.
