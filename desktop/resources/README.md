# Bundled UI font resources

`fonts.json` pins the original Noto Sans SC variable TTF and Inter variable WOFF2 by upstream commit, exact byte size and SHA-256. Their unmodified SIL OFL 1.1 license files are in `licenses/`.

Development startup (`npm run dev` or `npm run tauri dev`) only checks local cached files. It never starts a font download. Missing fonts produce an explicit system-font fallback message and do not block the window. Corrupted cached bytes still fail explicitly and are not silently overwritten. The running application only requests local font resources and installs no system font.

`npm run fonts:prepare` explicitly prepares missing fonts from the pinned upstream URLs; valid cached files work offline. Each download has a 60-second limit and can be cancelled. Errors produce a plain message and nonzero exit. `npm run build` keeps this strict preparation step: a release cannot silently omit the approved fonts. Build-time network access for initially missing resources remains necessary; it is not a development-startup prerequisite.

Generated binaries are ignored by Git and included as local production assets. Original licenses are copied alongside them. No font is edited or subset by this project. The two font files add 18,125,372 raw bytes before packaging/compression. P07-04 will record actual installer composition and sizes. The older P07-01 dependency notices describe the historical no-font delivery; this manifest and exact license files supplement them.
