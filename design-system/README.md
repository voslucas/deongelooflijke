# De Ongelooflijke

The visual language of **De Ongelooflijke Podcast** (EO / NPO Radio 1): journalist David Boogerd and theologian Stefan Paas talking with remarkable guests about faith in an increasingly unbelieving Netherlands — and its newsletter, *De Ongelooflijke* on Substack: “De wereld begrijpen – door geschiedenis, kunst en geloof.”

Built from the brand's public sources (7 Nov 2026): the Substack theme's CSS variables and fonts, the podcast artwork (an old engraving of a bearded saint wearing a halo and headphones) and the EO wordmark. Nothing here was invented except the dark theme and two contrast fixes, both noted below.

## Content fundamentals

- **Language:** Dutch, conversational but serious. Titles are often a question or a quote: *“Is Nederland klaar voor de oorlog van morgen?”*, *‘Het is tijd voor radicale figuren’*.
- **Names:** always *De Ongelooflijke Podcast* (capital D, O, P) in full; *De Ongelooflijke* for short. Never “Ongelooflijke podcast”.
- **Episode titles:** `#327 – Title`. The number always leads, in the UI font.
- **People:** Stefan Paas is “vaste gast”, David Boogerd “presentator”. Guests are introduced by role first: *militair expert Martijn Kitzen*.
- **Tone:** curious, not preachy. Questions over statements; no exclamation marks in interface copy.

## Visual foundations

**Old engraving meets modern listening.** The artwork pairs a 17th-century cross-hatched saint with white line-drawn headphones and halo; the system does the same with a classical serif on parchment plus one bright modern accent.

- **Ground:** `parchment` everywhere; `parchment-2` for cards. No pure white pages.
- **Ink:** `ink` for text, `ink-muted` for metadata. Substack's own grey (#757575) fails contrast on parchment (3.6:1), so `ink-muted` (#5e5549) replaces it.
- **Gold & engraving:** `gold` is the artwork's ground; use it as a fill (chart bars, badges, the medallion) with `engraving` text on it. As text on parchment, use `gold-deep`.
- **One accent:** `violet` (the EO / wordmark violet, #8720f7) for links, focus, the active filter and search highlights. Never as a large background except the wordmark's own blob; never next to gold at equal weight.
- **Borders, not shadows:** hairlines in `rule`; cards are flat `parchment-2` with `radius-md`.
- **Dark (“Nacht”):** a warm near-black ground with parchment text; violet lifts to #b88cff.

## Typography

- **Lora** (Google Fonts) — display and headings, 600–700. The Substack's heading preset (“fancy serif”).
- **Spectral** (Google Fonts) — body and quotes, 400. The Substack's body preset (“classic serif”).
- **System UI sans** — numbers, labels, filters, tables. Episode numbers and durations always set here with tabular numerals.

## Iconography & imagery

- **The saint** (`Logos/ongelooflijke-heilige.png`) is the face of the show. Show it round (`radius-pill`) or square, never cropped through the halo, never recoloured.
- **The wordmark** (`Logos/ongelooflijke-wordmark-eo.png`) is white text over a violet blob with the EO logo: place it only on `engraving` or `violet-deep` grounds.
- Icons: simple 1.5px line icons in `ink`, echoing the white line-drawing of the headphones.
- No stock photography; guest portraits are not part of the system.

## Usage

```css
body { background: var(--parchment); color: var(--ink); font: 18px/1.6 "Spectral", Georgia, serif; }
h1, h2 { font-family: "Lora", Georgia, serif; font-weight: 600; }
a { color: var(--violet); }
.ep-number { font-family: system-ui, sans-serif; font-variant-numeric: tabular-nums; color: var(--gold-deep); }
```
