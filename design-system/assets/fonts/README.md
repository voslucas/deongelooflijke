# Local web fonts

Lora and Spectral are bundled here and copied to `assets/fonts/` by both site
builders. Builds and visitors do not need Google Fonts access. `fonts.css` uses
relative WOFF2 URLs, the original Unicode subsets, and `font-display: swap`.

Downloaded on 23 November 2026 from the Google Fonts CSS API using this request:

<https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,500;0,600;0,700;1,500&family=Spectral:ital,wght@0,400;0,600;1,400&display=swap>

The response was requested with a Chrome 131 user agent for WOFF2 support. Each
font file retains its upstream filename; repeated URLs share one local file.
All returned subsets are included so accented names and non-Latin text retain
the same coverage. Browsers download only the subsets used by the page.

Lora: normal 500/600/700 and italic 500. Spectral: normal 400/600 and italic 400.
Both families use the SIL Open Font License 1.1; the accompanying license files
come from `ofl/lora/OFL.txt` and `ofl/spectral/OFL.txt` in
<https://github.com/google/fonts>.

To update, request the same CSS with a modern browser user agent, download every
`fonts.gstatic.com` URL, replace those URLs with the local filenames, and refresh
the licenses. Commit the fonts and stylesheet together. Normal builds only copy
these files and never download them.
