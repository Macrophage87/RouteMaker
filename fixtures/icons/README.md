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

## Note and stop icons (2026-11-10)

The twelve icons of route notes and stops (Stephen 2026-11-10: "Allow both", "We can use noto"), drawn as
pictures by default (`frontend/src/app/iconArt.tsx`, Vite `?url`: each a file of its own, shown in an `<img>`).
Downloaded 2026-11-10 from the same commit, `2D/svg/emoji_u<code>.svg`, into an empty directory and read before
they were copied in: `<svg>` with paths, groups and gradients, no script, no event attribute, no `href` but the
files' own `#` gradient ids, no external reference. Committed exactly as downloaded;
`frontend/src/lib/stopIcons.test.ts` holds the sha256 and those checks. Same licence (Apache 2.0, the notice above).

| File | Emoji | Bytes | sha256 |
| --- | --- | --- | --- |
| `noto-emoji-u1f374.svg` | U+1F374 fork and knife | 52,617 | `20aad3b1d514df37e7e9a94a16d681db11f1e3aa79024e031e1b8b69c666f115` |
| `noto-emoji-u1f3de.svg` | U+1F3DE national park | 9,237 | `089a1527f476a23ecba055b59edbe4d0225c06d1c53dcc1fb6967006f3459c75` |
| `noto-emoji-u1f4a7.svg` | U+1F4A7 droplet | 852 | `d4751fed323d453bc85a3366c01f1a0bf0f5ca5260bf48e6eb4b150c2af86dfa` |
| `noto-emoji-u1f4cd.svg` | U+1F4CD round pushpin | 1,233 | `c410eebb03aa1ac88d10563ca204f118e79303f6d4c7294945e1165766679fbf` |
| `noto-emoji-u1f4f7.svg` | U+1F4F7 camera | 4,331 | `7e0572c943b5a8d2b1e11ecebda3521f40dd37ae10578a9d9d59a8e5945a6895` |
| `noto-emoji-u1f527.svg` | U+1F527 wrench | 2,371 | `585050ccfcdaa032b836e008b71995086b4f734352cf6ab933d173e8add83976` |
| `noto-emoji-u1f573.svg` | U+1F573 hole | 45,050 | `0b8176881c391b9586f34934f45d95db9b0328d07047b111dd1619a6fc8e2f58` |
| `noto-emoji-u1f697.svg` | U+1F697 automobile | 3,745 | `0ed788aa0d922d69a031b7ece7e862e254b9cd07e3c7e6974e0f5ac5694cb549` |
| `noto-emoji-u1f6a7.svg` | U+1F6A7 construction sign | 9,805 | `cde40e90038b77fdeeefae35deb5c0f002e57d02619a4b2f9d0398da39a74103` |
| `noto-emoji-u1f6bb.svg` | U+1F6BB restroom | 2,813 | `7c1684ce488d8cc18946f651a313fcbd5203387ffaac48c57e44fc95ad07b244` |
| `noto-emoji-u2615.svg` | U+2615 hot beverage | 3,662 | `5830ae818458ee3c51208af6196a8a6c3d2a27e652aed2380c0b26a39d13d9dc` |
| `noto-emoji-u26a0.svg` | U+26A0 warning sign | 2,324 | `040e0a04356c12994f61a7011f47c7f278394f039feb01b5f3b2f82be3c7cc1f` |
