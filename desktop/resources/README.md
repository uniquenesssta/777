# Bundled UI font resources

`fonts.json` pins the original Noto Sans SC variable TTF and Inter variable WOFF2 by upstream commit, exact byte size and SHA-256. Their unmodified SIL OFL 1.1 license files are in `licenses/`.

`npm run build`, `npm run dev`, and the desktop development launcher prepare and verify `public/fonts/`. First preparation needs access to the pinned upstream URLs; valid cached files work offline. Wrong cached or downloaded bytes fail explicitly. Generated binaries are ignored by Git and included as local production assets; the running application makes no font CDN requests and installs no system font. Licenses are copied alongside them. No font is edited or subset by this project.

The two font files add 18,125,372 raw bytes before Tauri packaging/compression. P07-04 will record actual installer composition and sizes. The older P07-01 dependency notices describe the historical no-font delivery; this resource manifest and the exact license files supplement them for P07-03.
