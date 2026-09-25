# Sandplanet Marine — Brand Assets & Company Details

Branding pack for the Sandplanet Marine app (sister to Planet). Every generated document
and every screen references THESE files and values. Nothing is hand-drawn or retyped.

## Company details (authoritative — bake into templates/config)
- Legal name:        SANDPLANET MARINE PRIVATE LIMITED
- Brand name:        SANDPLANET MARINE
- Registration no.:  C21442026
- Date of registration: 16 June 2026
- TIN:               1184934
- Registered address: Fehiali, Gn. Fuvahmulah, Republic of Maldives
- Parent group:      Sand Planet Pvt Ltd (marine subsidiary)

## Logo files — in the repo at `backend/pdf_templates/assets/marine/`
- `spm-logo.png`            — full lockup (emblem + wordmark), transparent, 1317×960. Primary.
- `spm-emblem.png`          — circular emblem only, transparent, ~888×852. Favicon / app icon / small marks.
- `spm-wordmark.png`        — "SANDPLANET MARINE" wordmark, transparent (for light backgrounds).
- `spm-wordmark-white.png`  — wordmark in white (for navy / dark backgrounds).

NOTE ON FORMAT: these were extracted from a PNG raster (white background removed, then upscaled),
so they are high-res but not vector. For crisp print at any size, obtain the ORIGINAL VECTOR file
(AI / EPS / SVG / PDF) from the logo designer and replace these. Until then, use the emblem/logo at
displayed sizes at or below their pixel dimensions and they stay sharp.

## Palette (sampled from the logo)
- Marine navy   #0E1C29   darkest — the bar-chart marks, deep text
- Deep blue     #16527E   primary brand navy (shared with parent Sand Planet)
- Ocean blue    #2E6FA6   mid ring / body accents
- Wave blue     #407FAF   the wave and lighter ring
- Sky blue      #29ABE2   bright accent / interactive (shared with parent)
- Mist          #EAF3F9   soft fills
- Paper         #FFFFFF
(The two brands share the sky/navy family so Planet and Sandplanet Marine read as one group.
Marine leans a touch cooler/oceanic via the wave blues.)

## Type (match the parent for group consistency)
- Display: Barlow Condensed (bold, uppercase, tracked) — headings, wordmark
- Body:    Inter — everything else
- Mono:    IBM Plex Mono — document references, quantities
(Environment fallbacks when rendering here: DejaVu Sans Condensed / Carlito / DejaVu Sans Mono.)

## Convention for the app (same as Planet)
- Store these under one brand path (static assets or a Spaces "brand/" prefix).
- Every document template and the app header import the logo from that one path — change once, updates everywhere.
- Horizontal lockup (emblem left + wordmark) = document header + app top bar default.
- Emblem alone = favicon, app icon, small UI marks.
- On dark/navy backgrounds use the white wordmark; the emblem keeps its colours on any background.
- SIZE THE EMBLEM EXPLICITLY in templates (e.g. fixed mm/px) so it never overflows — same lesson as the parent brand.

## Letterhead block (for document headers)
SANDPLANET MARINE PRIVATE LIMITED
Fehiali, Gn. Fuvahmulah, Republic of Maldives
Reg. C21442026 · TIN 1184934
