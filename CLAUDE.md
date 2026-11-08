# Design and coding instructions — Ongelooflijk Archief

Read this before changing anything in the site. The brand book is `design-system/README.md`; the values are `design-system/tokens.json`. This file says how to apply them in code.

## 1. Brand in one paragraph

Old engraving meets modern listening. The show's artwork is a 17th-century cross-hatched saint wearing a white halo and headphones on a gold ground. The site does the same: a classical serif on warm parchment, dark-brown ink, gold fills, and **one** bright modern accent, the EO violet. It is a reference archive, so it reads like a well-set book with tools in it — not a dashboard and not a marketing page.

## 2. Tokens (never hard-code colours)

Use the CSS custom properties from `design-system/tokens.css`. Every colour must come from a token so both themes work.

| Token | Use for | Never use for |
| --- | --- | --- |
| `--parchment` | Page background | — |
| `--parchment-2` | Cards, panels, inputs, transcript fragments | Page background |
| `--parchment-3` | Hover, bar-chart tracks | Text |
| `--rule` | Hairlines, dividers, table rows | Text |
| `--ink` | Body text, headings | — |
| `--ink-muted` | Dates, durations, captions, axis labels | Long body text |
| `--gold` | Chart bars, guest avatars, badges, “hit” bingo cells, the medallion | Text on parchment (too light) |
| `--gold-deep` | Episode numbers, eyebrows, Stefan Paas in speaker charts | Large fills |
| `--engraving` | Footer, player bar, host avatar, “boek” badge | Text on parchment |
| `--violet` | Links, focus rings, active tab underline, search hits, timestamps, the first guest | Big backgrounds |
| `--violet-deep` | Filled buttons and chips with white text | Text |
| `--teal`, `--rose` | Second and third guest in speaker charts only | Anything else |
| `--mark` | `<mark>` hits and the active transcript line | — |

Rules:
- Text on `--gold` is always `#3e2b16` (engraving brown), never white.
- Text on `--violet-deep` and `--engraving` is white or parchment.
- Gold and violet never appear at equal weight side by side. Gold carries data; violet means “you can click / this is selected”.
- The two dark-theme blocks in `tokens.css` must stay in sync with the light `:root` block. A colour defined only in a dark block is a bug.
- Speaker colours are fixed by role: **David Boogerd = `--ink`**, **Stefan Paas = `--gold-deep`**, guests = `--violet`, `--teal`, `--rose` in order. Keep this everywhere (river, legends, transcript names, tables).

## 3. Typography

| Role | Face | Where |
| --- | --- | --- |
| Display | **Lora** 600–700 | `h1`–`h3`, person names in cards, big numbers in fact rows, top-5 lists |
| Body | **Spectral** 400 | Descriptions, summaries, transcript text, quotes (italic) |
| Interface | system UI sans | Nav, filters, buttons, chips, metadata, tables, chart labels |

- Episode numbers (`#327`), durations, timestamps and all columns of digits: UI sans with `font-variant-numeric: tabular-nums`.
- Eyebrow labels (`.label`, `.epno`): UI sans 600, 12–15px, uppercase, `letter-spacing: .08em`.
- Headings get `text-wrap: balance`. Body copy stays under ~66ch.
- Fonts load from Google Fonts with Georgia/system fallbacks; do not add other families.

## 4. Layout and components

- One content column, `max-width: 1120px`, side gutter `max(16px, env(safe-area-inset-*))`. Detail pages use a main column plus a 300px sidebar (`.detail`), stacking below 900px.
- **Borders, not shadows.** Separation is a 1px `--rule` line. Cards (`.panel`) are flat `--parchment-2` with 10px radius; only use them for sidebar groups and grouped stats, not for every block.
- Radii: 4px badges, 10px cards and inputs, 999px chips, pills and avatars.
- **Episode row (`.ep`)**: number column (gold-deep) · title in Lora · meta line (date · guests) · snippet · theme chips · duration on the right. Reuse `epRow()` for every list of episodes.
- **Person card (`.person`)**: initials avatar (gold for guests, engraving for hosts) + Lora name + role · count.
- **Fact row (`.facts`)**: 4 big Lora numbers with a small UI caption, divided by hairlines. Use at the top of overview pages only.
- **Badges**: `.badge` (gold) for episode format; `.mcat-*` for mention categories; `.demo` (dashed gold-deep outline) for anything showing example data.
- **Charts**: hand-drawn SVG (`vbars`, `hbars`, `lines`, `scatter`, `spark`). Bars are `--gold` (or `--violet` for a second measure), gridlines `--rule`, labels `--ink-muted`. Every number on an axis must be a value the scale reaches. No chart libraries.
- **Player bar**: fixed to the bottom, `--engraving` ground, gold play button, the speaker river as scrubber with a white playhead.
- Icons: simple 1.5–2px line icons in `currentColor`. No emoji in the UI.
- The saint artwork is shown round or square, never cropped through the halo, never recoloured. The white wordmark only on `--engraving` or `--violet-deep`.

## 5. Voice and copy

- Interface language is **Dutch**. Plain, curious, no exclamation marks (the bingo “Bingo!” is the one joke).
- Name things as listeners know them: *Afleveringen, Personen, Thema's, Statistieken, Genoemd, Wie zei het?*.
- Always write *De Ongelooflijke Podcast* in full on first use; *De Ongelooflijke* after.
- Hosts: David Boogerd is *presentator*, Stefan Paas is *vaste gast*.
- Every view that shows simulated data carries a `.demo` “Voorbeelddata” badge and one `.demonote` sentence saying what is simulated. Never remove these until the data is real.

## 6. Code conventions

- The site is **one self-contained HTML file**: inline CSS and JS, data inlined as JSON in `<script id="data" type="application/json">`, logos as data URIs. No build tools, frameworks or runtime fetches. External requests allowed: Google Fonts only.
- Routing is hash-based with plain names: `#start`, `#zoeken`, `#personen`, `#themas`, `#statistieken`, `#genoemd`, `#wie-zei-het`, and detail pages `#e-<nr>`, `#p-<slug>`, `#t-<slug>`, `#m-<slug>`. No `#/path` or query strings.
- Views are functions `viewX()` that set `app.innerHTML`; always pass user or data text through `esc()`.
- Slugs: `slug()` (lower-case, accents stripped, non-alphanumerics → `-`).
- Search matching: `norm()` (lower-case, accents stripped) plus `wre(term)` for word-start matches.
- Must work at 400px wide without horizontal scrolling; wide tables go in `.scroll`.
- Must work in light and dark (`prefers-color-scheme` and `data-theme`).
- Visible focus states (`outline: 2px solid var(--violet)`), real `<button>`s for actions, `<a href>` for navigation, `prefers-reduced-motion` respected.

## 7. Where the data comes from

- `data/episodes.json` → `D.eps[]` with keys: `n` number, `t` title (without “#n -”), `d` date, `s` seconds, `x` description, `r` recommended episode numbers, `id`/`sl` NPO page id and slug, `g` guests, `p` Stefan Paas present, `sj` people discussed, `th` themes, `f` format, `q` quotes, `mp3`. `D.bios` holds short guest bios.
- The transcript layer (`transcriptFor(e)`) and mentions layer (`mentionsFor`) currently **generate** data. Replace them with real data following `docs/transcript-schema.md`; the UI reads only the object shape described there, so views do not change.

## 8. Checklist before you ship a change

- [ ] Colours from tokens only; both themes checked.
- [ ] Text contrast ≥ 4.5:1 (3:1 for 24px+ and for chart marks).
- [ ] Phone width (400px) has no sideways scroll.
- [ ] New simulated numbers are badged “Voorbeelddata”.
- [ ] `python scripts/4_split_data.py && python scripts/5_build_site.py` run and `site/dist/index.html` opened in a browser with no console errors.
