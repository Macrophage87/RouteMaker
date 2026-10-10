# Bundled icons

The record OWNER-DECISIONS 310 asks for ("Record the sha and licence in fixtures, and cite it
on the sources page"). The file itself lives with the front end, which inlines it; the full
reference is docs/SOURCES.md, "Noto Emoji skull and crossbones".

| File | What | Source | Licence |
| --- | --- | --- | --- |
| `frontend/src/icons/noto-emoji-u2620.svg` | the skull and crossbones (U+2620) of the Avoid-rated junction marker (309, 310) | Noto Emoji, `2D/svg/emoji_u2620.svg` at commit `e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e`, <https://raw.githubusercontent.com/googlefonts/noto-emoji/e20cbc2bbec1926686be9f9bee7d1d2cfa1fea0e/2D/svg/emoji_u2620.svg> | **Apache 2.0**, Google (the directory's `2D/svg/LICENSE`; notice in `frontend/src/icons/NOTICE-noto-emoji.txt`, full text in `frontend/src/icons/LICENSE-Apache-2.0.txt`) |

Downloaded once, 2026-10-10, with the owner's approval of 13:57 UTC that day ("Yes", to
downloading the Noto Emoji skull-and-crossbones SVG). The path first named, `svg/emoji_u2620.svg`,
answers 404 at that commit: the repository keeps its SVGs under `2D/svg/` now, and this is the
same glyph's file there. Committed exactly as downloaded:

| File | Bytes | sha256 |
| --- | --- | --- |
| `noto-emoji-u2620.svg` | 8,320 | `4baff1c033110775d495b6fe6da05a7bdf94452af12f8a9207c00de28364535e` |

It was downloaded into an empty directory and read before it was copied in: `<svg>`, `<g>`,
`<path>` and `<ellipse>` with inline fills, no script, no event attribute, no `href`, no
external reference. `frontend/src/lib/avoidJunctions.test.ts` holds the sha256 and those checks.
