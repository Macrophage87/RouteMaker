/**
 * The stress overlay's paint definition.
 *
 * Kept as data rather than as inline style calls so that it can be asserted:
 * the accessibility rule is that nothing encodes meaning in colour alone, and a
 * rule that lives only in a reviewer's memory is one dash width away from being
 * broken. Each tier therefore carries a dash pattern and a label as well as a
 * colour, which also makes the overlay legible in the printed black and white a
 * marshal actually carries.
 *
 * Relative luminance decreases monotonically as stress rises, so the ordering
 * survives greyscale printing rather than running through hues that flatten
 * into the same grey. The test computes that luminance from the colour itself;
 * an earlier version compared a `lightness` number typed by hand beside each
 * colour, which meant the palette could violate the property while the test
 * passed. It did: LTS4 was the darkest tier of the four and sat eight grey
 * levels from LTS1, so on a marshal's black-and-white sheet "comfortable" and
 * "heavy traffic" printed the same.
 *
 * Each tier also carries a casing: a solid line drawn under it, two pixels
 * wider, in a colour chosen to stand apart from both the tier and whatever the
 * line is drawn over. The calm tiers are light greens, and on the base map
 * they are drawn over parkland, woods and scrub that are the same light greens
 * (LTS 1 against the park fill was 1.00:1), so without the casing the calmest
 * streets - the ones this map exists to find - were the invisible ones. A dark
 * casing under LTS 1 and 2 and a white one under LTS 3 and 4 keeps every tier
 * at least 3:1 from the map (WCAG 1.4.11's figure for graphics) and from both
 * themes' panel behind the legend; stressContrast.test.ts measures that
 * against the base map's own fill colours.
 */

import { MASS_SOURCE_ID, massHides, massLayers } from "./massStyle.js";

// The tiers' shapes: what tells them apart without colour. Weight rises with
// stress (OWNER-DECISIONS 274, 283: "If I didn't see the key, I'd think that
// LTS4 was lower stress"): ink - the share of the line that is drawn (the dash
// duty cycle) times its width - rises strictly from LTS 1 to Avoid. LTS 1 is a
// thin solid line; LTS 2 and LTS 3 are dashed, LTS 3 with the shorter dash and
// the wider line; LTS 4 is near-solid and heavy (long dashes, a pixel's gap per
// five); Avoid is the widest and keeps a dash-dot nothing else has. Every dash
// list has an even length (see below).
//
// A dash's gaps show the casing under it, so a gap is only as calm as its share
// of the line times the casing's contrast with the line ("harshness",
// gapHarshness below). OWNER-DECISIONS 292: LTS 3's [2, 1] over a near-black
// casing ("that black in the LTS3 is a bit too harsh, especially with LTS4 being
// white") was the harshest pattern on the map, 1.51 against LTS 4's 0.67. Its
// dash keeps its length (8.5 px, the short dash that is LTS 3's own) and its gap
// is cut to 0.4 of the width (1.7 px, a sixth of the line) over a softer brown
// casing: 0.60, no harsher than LTS 4. stressSalience.test.ts holds harshness
// non-decreasing from LTS 3 to LTS 4 to Avoid in every palette, plain and strong.
// The labels are the owner's step words (OWNER-DECISIONS 441l, 441j: "5 is just avoid"), the
// ones the road panel and its editor use (core/segment_info.py TIER_WORDS); 460.8-11 switched
// the legend to them from its own.
const TIER_SHAPES = [
  // A solid line is `null`, never [1]: a one-entry dash array is an odd list,
  // which SVG (the legend) repeats into [1, 1] - a dashed swatch for a line
  // the map draws solid (OWNER-DECISIONS 279). Every dash here has an even length.
  { tier: 1, label: "Comfortable for everyone", short: "LTS 1", dash: null, width: 2.5 },
  { tier: 2, label: "Fine for adults", short: "LTS 2", dash: [4, 1], width: 3.25 },
  { tier: 3, label: "For experienced cyclists", short: "LTS 3", dash: [2, 0.4], width: 4.25 },
  { tier: 4, label: "High stress: busy, fast traffic", short: "LTS 4", dash: [8, 1], width: 5 },
  // Not a Furth tier: legal for a bicycle and best avoided (the owner's fifth
  // category, 2026-09-27): the widest line and a dash-dot nothing else uses.
  { tier: 5, label: "Avoid", short: "Avoid", dash: [5, 1, 0.5, 1], width: 6.5 },
];

/**
 * THE STRESS COLOURS, in one place. The owner, 2026-09-29: "Also, let's change
 * the color scheme. I like LTS 1 and 2. Maybe yellow and orange for LTS 3,
 * orange and red for LTS 4, and red and black for Avoid." (OWNER-DECISIONS
 * 74). LTS 1 and 2 are kept as they were; two readings of "X and Y" were built
 * for the owner to choose between. OWNER-DECISIONS 351 (2026-10-04, on the
 * warm palette's LTS 3, which "looks unpaved" beside the brown unpaved ramp,
 * 350): "2 tone is better", "Make two-tone the default". So the default is
 * "twotone", in the owner's colours, and "blended" (a link's `?palette=warm`)
 * stays as an option. Where the two-tone colours break a rule the warm palette
 * keeps, the break is reported, not fixed: testSupport/defaultConflicts.ts
 * lists them, and defaultPalette.test.ts holds the default to every other rule
 * and to exactly those. 371 took two of the fixes proposed: LTS 3 and LTS 4 are
 * ringed in near-black (#1c1917), which makes both 3:1 on the base map, and the
 * yellow is #f3c81a (#f2c21b before), 1.44:1 from LTS 4 for a deuteranope.
 * What is left: the line on its own edge inside the ring, the greyscale order,
 * LTS 4 less saturated than LTS 3, Avoid against LTS 4 under deuteranopia, and
 * the same-tier paved/unpaved pairs listed there.
 *
 * - "blended": one colour per tier between the two named - LTS 3 amber (over
 *   a dark casing, since amber is not 3:1 on the base map's greens), LTS 4 a
 *   saturated red (over white) and Avoid a near-black (over a bright red
 *   casing). Relative luminance still falls tier by tier (0.57, 0.28, 0.23,
 *   0.12, 0.003), so greyscale print keeps the order; LTS 2 and 3 are only 1.17:1 apart in grey, where their dashes
 *   (long, even) tell them apart - an amber dark enough for 1.4:1 is brown.
 *   OWNER-DECISIONS 274 (2026-10-03: "LTS3 looks more distinctive than LTS4
 *   and Avoid is hard to tell apart"): LTS 4 was a dark, dull red (#a32814,
 *   CIELAB chroma 64, the same as LTS 3's amber) and Avoid a dark maroon
 *   (#4a0810) beside it. LTS 4 is now a saturated red (#c80018, chroma about 80, 15
 *   more than the amber) and Avoid a near-black on a coral-red casing, wider
 *   still and dashed as nothing else is, so the pair differ in shape, width
 *   and casing as well as hue; stressContrast.test.ts holds the salience order
 *   and that separation.
 * - "twotone" (the default since 351): the first colour as the line, the
 *   second as its casing - LTS 3 yellow on orange, LTS 4 orange on red, Avoid
 *   red on black, LTS 3 and LTS 4 ringed in near-black (371). Closer to the
 *   owner's words; inside the ring the line on its edge is 1.53:1 (LTS 3) and
 *   2.34:1 (LTS 4), and the greyscale order is lost (defaultPalette.test.ts and
 *   testSupport/defaultConflicts.ts hold exactly what is reported).
 * - "cvd" (OWNER-DECISIONS 208): the colour-blind-friendly option a rider
 *   switches to in the panel. Not a reading of the owner's colours: it is
 *   chosen by measurement to stay apart under protanopia, deuteranopia and
 *   tritanopia (Machado 2009, severity 1.0). The comfortable tiers are light
 *   and mid blue, LTS 3 a burnt orange, LTS 4 a dark red and Avoid a
 *   blue-black: blue against orange is the pair all three deficiencies keep,
 *   and the lightness falls tier by tier, so greyscale order holds too.
 *   Every adjacent pair is CIEDE2000 20 or more apart under normal vision and
 *   under each simulation (stressContrast.test.ts; the table is in
 *   docs/DEVELOPMENT.md, "The accessibility switch and the colour-blind-friendly
 *   palette"). The blue-black is not a neutral black on purpose: a protanope
 *   sees LTS 4's dark red as near-black, and a neutral black Avoid beside it
 *   measures about 17 apart (#000000, 16.9 under protanopia). LTS 4 and
 *   Avoid are told apart by casing too: white under LTS 4, light yellow under
 *   Avoid.
 */
export const PALETTES = {
  blended: {
    1: { color: "#9ed3ac", casing: "#2f5d47" },
    2: { color: "#57a06c", casing: "#1a2638", gap: "#7a8fa3" },
    3: { color: "#bf730b", casing: "#45290a" },
    4: { color: "#c80018", casing: "#ffffff" },
    5: { color: "#14040a", casing: "#ee3b2c" },
  },
  twotone: {
    1: { color: "#9ed3ac", casing: "#2f5d47" },
    2: { color: "#57a06c", casing: "#1a2638", gap: "#7a8fa3" },
    // 371: the yellow a shade lighter (#f2c21b before), so LTS 3 and LTS 4 are 1.4:1 apart for a deuteranope;
    // LTS 3 and LTS 4 ringed in near-black, so both are 3:1 on the base map; Avoid ringed in the legend only.
    3: { color: "#f3c81a", casing: "#f28c28", ring: "#1c1917" },
    4: { color: "#f28c28", casing: "#c81e1e", ring: "#1c1917" },
    5: { color: "#d42020", casing: "#111111", legendRing: "#9aa0a6" },
  },
  cvd: {
    1: { color: "#d2eafc", casing: "#0a1a2f" },
    2: { color: "#5d99d2", casing: "#0a1a2f", gap: "#a7b4c1" },
    3: { color: "#cd4b0a", casing: "#0a1a2f" },
    4: { color: "#6a0a06", casing: "#ffffff" },
    // Avoid's casing is a light yellow (Okabe-Ito #f0e442) of its own, as the
    // default palette's Avoid has its red: on white like LTS 4's, the pair were
    // 1.56:1 apart on the same casing (the a11y review's SF5), and this palette is
    // the one the accessibility switch turns on. Not white, and not LTS 3's
    // orange; 14.8:1 from the blue-black line (stressSalience.test.ts holds the
    // pair apart in casing, and Avoid's line 3:1 from it).
    5: { color: "#08081e", casing: "#f0e442" },
  },
};

/**
 * The outline on a half step's dash where the dash is too close to its line (458b), by palette and the
 * half step's lower level: the default palette's 3.5 (LTS 4's orange dash on LTS 3's yellow, about
 * 1.5:1) gets a near-black outline, and the colour-blind palette's 4.5 (Avoid's blue-black dash on LTS
 * 4's dark red, about 1.6:1) a white one. Each is at least 3:1 from both the dash and the line
 * (halfSteps.test.ts; HALF_OUTLINE_MIN_CONTRAST). See `halfStepLayers`.
 */
export const HALF_OUTLINES = {
  twotone: { 3: "#1c1917" },
  cvd: { 4: "#ffffff" },
};

/** The palette the map uses unless the address or the accessibility switch asks for another. */
export const DEFAULT_PALETTE = "twotone";

/**
 * The palettes' names in a link (`?palette=`), which say nothing of who uses them
 * (OWNER-DECISIONS 321: "Make sure that the link text doesn't scream 'disability' in the
 * parameters."): "twotone" the default (since 351), "warm" the option that was the
 * default before, "cool" the blue-and-orange one the switch turns on. The names in the code stay as they were.
 * linkPalette.test.ts holds every name and value a link can carry to a denylist.
 */
export const PALETTE_LINK_NAMES = { blended: "warm", twotone: "twotone", cvd: "cool" };

/**
 * A link's palette value as the palette it names: the names above, and the older
 * values (`blended`, `cvd`) still read, silently, so a link already shared still works.
 * Nothing writes the older values.
 */
function paletteOfLinkValue(value) {
  const named = Object.entries(PALETTE_LINK_NAMES).find(([, name]) => name === value)?.[0];
  if (named) return named;
  return Object.hasOwn(PALETTES, value) ? value : null;
}

/**
 * The address's query with an older palette value (`blended`, `cvd`) renamed to its
 * neutral name (`warm`, `cool`), or null where there is nothing to rename. The page
 * writes it back into the address bar on load, so a rider who opens an old link and
 * copies the address does not pass the old value on (321: "any existing link flags of
 * this kind are renamed the same way"; the release re-check's S4).
 */
export function neutralPaletteSearch(search) {
  const match = /(^|[?&])palette=([a-z]+)/.exec(search ?? "");
  if (!match || !Object.hasOwn(PALETTE_LINK_NAMES, match[2])) return null;
  const name = PALETTE_LINK_NAMES[match[2]];
  if (name === match[2]) return null;
  return search.slice(0, match.index) + `${match[1]}palette=${name}` + search.slice(match.index + match[0].length);
}

/** The palette an address's query string names (`?palette=twotone`), or the default. */
export function paletteFrom(search) {
  return queryPalette(search) ?? DEFAULT_PALETTE;
}

/** The palette the accessibility switch turns on (OWNER-DECISIONS 208, 211). */
export const ACCESSIBILITY_PALETTE = "cvd";

/** Where the switch is remembered, per browser: "on" or "off". */
export const ACCESSIBILITY_STORAGE_KEY = "routemaker.accessibility";

/** With the switch on, each line is this much wider (pixels), and its casing this much wider than that. */
export const STRONG_WIDTH_EXTRA = 0.5;
export const STRONG_CASING_EXTRA_PX = 3;

/** The palette an address names (`?palette=cool`), or null when it names none this page has. */
export function queryPalette(search) {
  const match = /(?:^|[?&])palette=([a-z]+)/.exec(search ?? "");
  return match ? paletteOfLinkValue(match[1]) : null;
}

/** The browser's localStorage, or null where reaching it throws (blocked site data, some embedded views). */
function browserStorage() {
  try {
    return globalThis.localStorage ?? null;
  } catch {
    return null;
  }
}

/**
 * The palette to start with: the address's (`?palette=`), else the
 * colour-blind-friendly one when the accessibility switch is on, else the
 * default.
 */
export function resolvePalette(search, accessibility = false) {
  return queryPalette(search) ?? (accessibility ? ACCESSIBILITY_PALETTE : DEFAULT_PALETTE);
}

/**
 * A casing pushed to its extreme: black under a dark one, white under a light
 * one - for the calm tiers, whose casing is a halo against the park greens.
 * A busy tier's casing (LTS 3 and up, `keep`) is left as it is: it is what
 * shows in the tier's dash gaps, and black there is the harshness the owner
 * asked to be rid of (OWNER-DECISIONS 292; black under LTS 3 would make its
 * gaps harsher than LTS 4's white ones), while Avoid's is a colour of its own
 * (the default palette's red, OWNER-DECISIONS 274; the colour-blind-friendly
 * palette's light yellow, the a11y review's SF5), where black would put the
 * near-black line on black and white would give up the cue. The switch still
 * widens every line and casing.
 */
function strongerCasing(hex, keep = false) {
  if (keep) return hex;
  return relativeLuminance(hex) < 0.5 ? "#000000" : "#ffffff";
}

/**
 * How harsh a tier's dash gaps are: the share of the line that is gap, times
 * the contrast between the casing that shows in the gaps and the line
 * (OWNER-DECISIONS 292). 0 for a solid line.
 */
export function gapHarshness(tier) {
  if (!tier.dash) return 0;
  const gaps = tier.dash.filter((_, i) => i % 2 === 1).reduce((a, b) => a + b, 0);
  const all = tier.dash.reduce((a, b) => a + b, 0);
  return (gaps / all) * contrastRatio(tier.gap ?? tier.casing, tier.color);
}

/** Below this a casing is dark (a near-black), dark enough to be a faint line's edge. */
const DARK_CASING_LUMINANCE = 0.05;

/**
 * The tiers, with a palette's colours. With `strong` (the accessibility
 * switch) they are drawn stronger: lines half a pixel wider, the calm tiers'
 * casings black or white, and every casing a pixel wider again. Each tier
 * carries the casing's extra width (`casingExtra`) and whether it is drawn
 * strong (`strong`, which also widens the painted-lane rail), which the layers
 * and the legend read.
 */
export function tiersFor(palette, strong = false) {
  return TIER_SHAPES.map((shape) => {
    const colours = PALETTES[palette][shape.tier];
    const unpaved = UNPAVED_PALETTES[palette][shape.tier];
    // A busy tier's casing is kept by the switch (292), and so is LTS 2's blue edge (356: "a blue instead of black").
    const keep = shape.tier >= BUSY_MIN_TIER || shape.tier === 2;
    const casing = strong ? strongerCasing(colours.casing, keep) : colours.casing;
    const unpavedCasing = strong ? strongerCasing(unpaved.casing, keep) : unpaved.casing;
    const gravel = GRAVEL_PALETTES[palette][shape.tier];
    const gravelCasing = strong ? strongerCasing(gravel.casing, keep) : gravel.casing;
    return {
      ...shape,
      ...colours,
      casing,
      // What the dash's gaps show: the tier's own gap colour (356), else its casing.
      gap: colours.gap ?? casing,
      // The unpaved brown for this tier, the casing under it (OWNER-DECISIONS 302) and its gaps' colour.
      unpavedColor: unpaved.color,
      unpavedCasing,
      unpavedGap: unpaved.gap ?? unpavedCasing,
      // The gravel grey for this tier (GRAVEL_PALETTES), its casing and its gaps' colour.
      gravelColor: gravel.color,
      gravelCasing,
      gravelGap: gravel.gap ?? gravelCasing,
      // The outline on the half step above this level's dash, where it needs one (458b).
      halfOutline: HALF_OUTLINES[palette]?.[shape.tier] ?? null,
      ...(strong
        ? { width: shape.width + STRONG_WIDTH_EXTRA, casingExtra: STRONG_CASING_EXTRA_PX, strong: true }
        : { casingExtra: CASING_EXTRA_PX, strong: false }),
    };
  });
}

/**
 * LTS 2's edge and gaps (OWNER-DECISIONS 356, 2026-10-04: "For Lts 2 maybe use a
 * blue instead of black. Especially unpaved, LTS2 can almost be harsher than
 * LTS3."). A dash's gaps used to show the tier's casing, and LTS 2's was a
 * near-black (#17301f) under a mid green, so its gaps were harsher than the
 * busier tiers' (0.90 against two-tone LTS 3's 0.24). LTS 2 now has a dark
 * slate-blue edge (#1a2638, the halo that keeps it 3:1 on the base map) and a
 * steel-blue gap (#7a8fa3, drawn as its own solid line between the casing and
 * the dashes, `gap`; the colour-blind-friendly palette's is a pale grey-blue,
 * #a7b4c1, beside its blue line), paved and unpaved. The 292 rule now runs from
 * LTS 1 up: harshness never falls as stress rises, paved and unpaved, in every
 * palette, plain and strong (stressSalience.test.ts, unpavedBrown.test.ts). The
 * blues stay clear of the route's #1d4ed8: 23.8 CIEDE2000 and 24 L* darker for
 * the edge, 22.6 and 19 L* lighter for the gap. A tier with no `gap` shows its
 * casing in its gaps, as before. The trade: LTS 2's green and its steel-blue
 * gaps are close in lightness (1.06:1), so in greyscale its dashes are faint and
 * LTS 2 is told from LTS 1 by its width and edge more than by its dash.
 */
/** Whether a tier has a gap colour of its own in some palette (only LTS 2, 356): only such a tier gets a gap layer. */
export function hasGapLayer(tier) {
  return [PALETTES, UNPAVED_PALETTES, GRAVEL_PALETTES].some((ps) => Object.values(ps).some((p) => p[tier].gap));
}

export function gapLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers
    .filter((tier) => tier.dash && hasGapLayer(tier.tier))
    .map((tier) => {
      const busy = tier.tier >= BUSY_MIN_TIER;
      return {
        id: `stress-gap-${tier.tier}`,
        type: "line",
        source: sourceId,
        "source-layer": STRESS_TILE_LAYER,
        filter: filters[`stress-gap-${tier.tier}`],
        paint: {
          // Solid, the line's width, under the dashes: what shows between them. Not drawn where the line is
          // faint (the casing is then a ring, FAINT), so a faint road is as it was.
          "line-color": byUnpaved(tier.unpavedGap, tier.gap, tier.gravelGap),
          "line-width": byZoom(tier.width, tier.width * FAINT.widthScale, busy, 0, (zoom) => zoomedOutLine(tier, zoom)),
          "line-opacity": byZoom(1, 0, busy),
        },
      };
    });
}

/**
 * UNPAVED ROADS AND TRAILS (OWNER-DECISIONS 302): "For unpaved, instead of the
 * stress colors we have earlier, just go with brown for everything, with darker
 * shades for more traffic stress and the same dashes." One brown ramp per
 * palette, light to dark from LTS 1 to Avoid; each tier keeps its own dash and
 * width (283), so the stress level still reads without colour, and the dotted
 * centre mark (UNPAVED_DASH, in the tier's unpaved casing) stays as the cue
 * that is not colour at all.
 *
 * The ramp is a lightness ladder: every step is 1.5:1 or more darker than the
 * last (greyscale print keeps the order) and 10 or more CIEDE2000 from it under
 * normal vision and each simulated deficiency - the most a five-step single-hue
 * ladder between a line light enough for a dark casing and one dark enough to
 * stand alone allows; the dashes and widths carry the rest. The light browns
 * (LTS 1, 2) sit on a dark brown casing, the dark ones (LTS 3 up) on a cream one,
 * so every line is 3:1 or more from its casing and every tier 3:1 from the base
 * map, and the gaps' harshness (292) still rises from LTS 3 to LTS 4 to Avoid.
 *
 * - blended: a sepia, the low-chroma earth browns of a sepia print, from a
 *   pale linen (#ebddd1) to a near-black umber. OWNER-DECISIONS 350 ("LTS3
 *   looks unpaved"): the warm tans before (#d9b98c to #33200d) were 10.4 and
 *   14.3 CIEDE2000 from the paved LTS 3 amber at LTS 2 and 3; the sepia is 20
 *   or more from it at every step under normal vision.
 * - twotone (the default): greyer browns (taupe), because that palette's paved
 *   LTS 3 is a yellow (#f3c81a since 371, #f2c21b before) a warm tan would sit
 *   on (6 CIEDE2000 under deuteranopia). Its LTS 1 is a pale taupe (#e6dad4; 350, 371): #d4bba6 was 9.1
 *   from the yellow under tritanopia. Every step is 22 or more from the yellow
 *   under normal vision and 15 or more under every vision.
 * - cvd: an ochre-olive ramp on the yellow side of the blue-yellow axis all
 *   three deficiencies keep: 30 or more CIEDE2000 from that palette's blue calm
 *   tiers under every vision, with the widest steps of the three (1.6:1 and up).
 *   Its LTS 3 is a duller brown (#7a6046; 350): the ochre #7e6028 was 4.5
 *   CIEDE2000 from the palette's paved LTS 3 orange under protanopia, and this
 *   is 12.5.
 *
 * stressSalience.test.ts holds all of this; the figures are in its diagnostics.
 */
export const UNPAVED_PALETTES = {
  blended: {
    1: { color: "#ebddd1", casing: "#3b2410" },
    2: { color: "#ac9888", casing: "#1a2638", gap: "#7a8fa3" },
    3: { color: "#7b6250", casing: "#f6ead2" },
    4: { color: "#543e2c", casing: "#f6ead2" },
    5: { color: "#2e2118", casing: "#f6ead2" },
  },
  twotone: {
    1: { color: "#e6dad4", casing: "#33231a" },
    // A shade lighter than #ac8b73 (the release re-check's SF-A): paved and unpaved LTS 2 were
    // one colour to a deuteranope (2.1); now 10.5 apart under every vision.
    2: { color: "#c2a698", casing: "#1a2638", gap: "#7a8fa3" },
    3: { color: "#7d604b", casing: "#f6ead2" },
    4: { color: "#53392a", casing: "#f6ead2" },
    5: { color: "#2b1c14", casing: "#f6ead2" },
  },
  cvd: {
    1: { color: "#e0c68a", casing: "#2a200c" },
    2: { color: "#bc9a52", casing: "#2a200c", gap: "#7a8fa3" },
    3: { color: "#7a6046", casing: "#f6ead2" },
    4: { color: "#544018", casing: "#f6ead2" },
    5: { color: "#2a200c", casing: "#f6ead2" },
  },
};

/**
 * GRAVEL GREY (the owner, 2026-10-21: "Maybe make natural surface trails brown and gravel grey?", after a gravel path
 * and a dirt trail looked identical on the map). An unpaved way the tiles do not call rough (their "rough": a natural
 * surface, or a rutted track or bad smoothness; `routemaker.stress.is_rough`) is gravel, compacted or a firm unpaved
 * surface, and is drawn in this grey ramp in place of the brown one, with the same dashes, widths and dotted mark;
 * brown is kept for natural surfaces. One ramp in every palette: greys are the same to every colour vision. Like the
 * brown ramp, every step is 1.5:1 or more darker than the last and 10 or more CIEDE2000 from it under every vision;
 * the light greys sit on a near-black edge (LTS 2 on its slate-blue one, 356), the dark ones on a pale grey edge.
 */
const GRAVEL_RAMP = {
  1: { color: "#bbbfc5", casing: "#1c1f23" },
  2: { color: "#92979d", casing: "#1a2638", gap: "#7a8fa3" },
  3: { color: "#60666d", casing: "#f4f5f6" },
  4: { color: "#3f4449", casing: "#f4f5f6" },
  5: { color: "#1e2124", casing: "#f4f5f6" },
};
export const GRAVEL_PALETTES = { blended: GRAVEL_RAMP, twotone: GRAVEL_RAMP, cvd: GRAVEL_RAMP };

/**
 * Whether a feature is an unpaved natural surface (the tiles' "unpaved" and "rough"): brown; other unpaved is gravel grey.
 * The tiles carry "rough" on every table built since NO-BIKE-PATHS (290, 291); on an older one, without the column, every
 * unpaved way draws grey here while the route line, which has no `rough` then, draws it brown.
 */
const isNatural = ["all", ["==", ["get", "unpaved"], true], ["==", ["get", "rough"], true]];

/**
 * A colour by surface: `natural` on an unpaved natural surface, `gravel` on any other unpaved way, else `paved`.
 * With no `gravel` (a caller that has one colour for every unpaved way) both unpaved kinds take `natural`.
 */
const byUnpaved = (natural, paved, gravel = natural) =>
  gravel === natural ? ["case", ["==", ["get", "unpaved"], true], natural, paved] : ["case", isNatural, natural, ["==", ["get", "unpaved"], true], gravel, paved];

/**
 * A path or trail whose surface OpenStreetMap does not give (OWNER-DECISIONS 376, A, from
 * PARK-TRAILS-investigation.md): a trail-class feature (the tiles' "trail") with no "unpaved"
 * at all, which the tiles leave out when the surface is unknown ("true" is unpaved, "false"
 * is paved). Park trails with no surface tag were drawn like a paved path, with a path's
 * rails and a dark edge; they may be either. It is a style only: nothing is closed.
 * Roads with no surface tag (nearly every street) are not this; they draw as they always did.
 * Nor is a trail beside a road (the tiles' "roadside", OWNER-DECISIONS 403: "Most trails near
 * a road are paved. There are minor exceptions."): it keeps the paved path's look, rails and all.
 */
const surfaceUnknown = ["all", ["==", ["get", "trail"], true], ["!", ["has", "unpaved"]], ["!=", ["get", "roadside"], true]];

/**
 * The surface-unknown line's shape (no colour in it): short, even dashes, a dash as long as
 * 0.8 of its gap (2 on, 1.5 off, in line widths), which no tier has (LTS 2 is long dashes
 * with short gaps, LTS 3 almost solid) and the unpaved mark is not (a dotted line drawn over
 * a solid brown one). It is drawn in LTS 1's own colours, as the line it is, with a dashed
 * edge of the same length, and with no path rails.
 */
export const UNKNOWN_SURFACE_DASH = [2, 1.5];

/**
 * What this browser remembers of the accessibility switch: true (on), false
 * (off, chosen), or null where nothing is stored, the value is not one this
 * page wrote, or storage throws.
 */
export function storedAccessibility(storage = browserStorage()) {
  try {
    const value = storage?.getItem(ACCESSIBILITY_STORAGE_KEY);
    return value === "on" ? true : value === "off" ? false : null;
  } catch {
    return null;
  }
}

/**
 * Whether the switch starts on: what the browser remembers, else whether the
 * system asks for more contrast, else off. The rider's own choice, on or off,
 * always wins; it is not the general default.
 */
export function resolveAccessibility(stored, contrastRequested = false) {
  return stored ?? contrastRequested;
}

/** Remember the switch for this browser; false when storage refused (it then lasts the visit). */
export function rememberAccessibility(on, storage = browserStorage()) {
  try {
    if (!storage) return false;
    storage.setItem(ACCESSIBILITY_STORAGE_KEY, on ? "on" : "off");
    return true;
  } catch {
    return false;
  }
}

// What the page is drawn in, which a rider can change without a reload: the
// accessibility switch, and the palette it and the address decide between.
// Nothing may keep the tiers from import time: read currentTiers() when
// drawing, and subscribePalette() to draw again (the source scan in
// lib/accessibilitySwitch.test.ts fails a module that imports a fixed list, or
// calls currentTiers(), furthTiers(), routeClasses() or legend() at its top
// level).
const locationSearch = typeof location === "undefined" ? "" : location.search;
const pinnedByAddress = queryPalette(locationSearch) !== null;
/** The rider's own choice of the switch (stored, or made this visit): null while there is none, and the system's request decides. */
let chosen = storedAccessibility();
let contrastMore = false;
let accessibility = resolveAccessibility(chosen, contrastMore);
let active = resolvePalette(locationSearch, accessibility);
/** @type {Map<string, ReturnType<typeof tiersFor>>} */
const tiersByStyle = new Map();
/** @type {Set<(name: string) => void>} */
const listeners = new Set();

function tell() {
  for (const listener of [...listeners]) listener(active);
}

/** The palette this page is using now. */
export function currentPalette() {
  return active;
}

/** Whether the accessibility switch is on. */
export function accessibilityOn() {
  return accessibility;
}

/** What the switch's state is down to: "chosen" by the rider, "contrast" (the system asks for more), or "default" (off). */
export function accessibilitySource() {
  if (chosen !== null) return "chosen";
  return contrastMore ? "contrast" : "default";
}

/** Whether the address (`?palette=`) chose the palette, which the switch does not override. */
export function paletteSetByAddress() {
  return pinnedByAddress;
}

/** A key that changes whenever what the tiers look like does: the palette, or the switch. */
export function styleKey() {
  return `${active}|${accessibility ? "strong" : "plain"}`;
}

/** The tiers, in the palette and strength in use. The same array until one of them changes. */
export function currentTiers() {
  const key = styleKey();
  let tiers = tiersByStyle.get(key);
  if (!tiers) {
    tiers = tiersFor(active, accessibility);
    tiersByStyle.set(key, tiers);
  }
  return tiers;
}

/** The Furth tiers (1-4), the ones ordered by luminance for greyscale print, in the palette in use. */
export function furthTiers() {
  return currentTiers().filter((t) => t.tier <= 4);
}

/**
 * Turn the accessibility switch on or off now and tell the subscribers; with
 * `remember` (the default) it is kept for this browser, and storage that
 * refuses leaves it set for the visit. On, the stress colours are the
 * colour-blind-friendly palette and the lines are drawn stronger; an address
 * that names a palette still decides the palette. `remember: false` is a
 * trial that leaves what is stored, and the system's say, alone.
 */
export function setAccessibility(on, { remember = true, storage } = {}) {
  const next = on === true;
  if (remember) {
    rememberAccessibility(next, storage);
    chosen = next;
  }
  apply(next);
}

function apply(next) {
  if (next === accessibility) return;
  accessibility = next;
  active = resolvePalette(locationSearch, accessibility);
  tell();
}

/** The media query for a request for more contrast: where the switch starts, until the rider chooses. */
export const CONTRAST_MEDIA = "(prefers-contrast: more)";

/** The parts of a `MediaQueryList` that are used. */
/** @typedef {{ matches: boolean, addEventListener?: Function, removeEventListener?: Function, addListener?: Function, removeListener?: Function }} MediaQuery */

let stopWatching = () => {};

/**
 * Follow the system's request for more contrast, now and as it changes (the
 * rider turns it on in the system's settings with the page open): with no
 * choice of the rider's own, the switch follows it. Returns the way to stop.
 * Called once at load with the window's own matchMedia; a test passes a
 * stand-in. A matchMedia that is missing or throws means no request.
 *
 * @param {((query: string) => MediaQuery) | null} [matchMediaImpl]
 */
export function watchContrast(matchMediaImpl = typeof matchMedia === "function" ? matchMedia : null) {
  stopWatching();
  stopWatching = () => {};
  /** @type {MediaQuery | null} */
  let query = null;
  try {
    query = matchMediaImpl ? matchMediaImpl(CONTRAST_MEDIA) : null;
  } catch {
    query = null;
  }
  const follow = (more) => {
    contrastMore = more === true;
    if (chosen === null) apply(contrastMore);
  };
  follow(query?.matches);
  if (!query) return stopWatching;
  const q = query;
  const onChange = (event) => follow(typeof event?.matches === "boolean" ? event.matches : q.matches);
  if (typeof q.addEventListener === "function") {
    q.addEventListener("change", onChange);
    stopWatching = () => q.removeEventListener?.("change", onChange);
  } else if (typeof q.addListener === "function") {
    q.addListener(onChange); // older Safari
    stopWatching = () => q.removeListener?.(onChange);
  }
  return stopWatching;
}

watchContrast();

/** Call `listener(name)` whenever the palette, or the strength the tiers are drawn at, changes; returns the way to stop. */
/** @param {(name: string) => void} listener */
export function subscribePalette(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** WCAG relative luminance of a hex colour, 0 (black) to 1 (white). */
export function relativeLuminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) =>
    c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Contrast ratio between two hex colours, per WCAG 2.x. */
export function contrastRatio(a, b) {
  const [hi, lo] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The basemap, served from a local PMTiles file rather than a tile provider. */
//
// The path is the one Caddy serves the archive at (Caddyfile, /basemap/*;
// docs/OPERATIONS.md, "The base map"). It is relative on purpose: the pmtiles
// protocol fetches it on the page's own thread, so the browser resolves it
// against the page and sends the same-origin Referer that the edge's hotlinking
// guard requires. The archive's embedded attribution names OpenStreetMap only,
// so the credit is stated here rather than read from it.
export const BASEMAP = {
  // Range requests against one file on our own disk: no third party sees which
  // routes are being looked at, which matters when some of them are for
  // unpermitted rides.
  protocol: "pmtiles",
  path: "/basemap/region.pmtiles",
  url: "pmtiles:///basemap/region.pmtiles",
  // Brief (OWNER-DECISIONS 306), and the first two of lib/credits.json as the
  // attribution control joins them, so MapLibre folds this into its one entry.
  attribution: '<a href="https://www.openstreetmap.org/copyright">© OpenStreetMap contributors</a> (ODbL) | Protomaps',
};

/**
 * THE STREET NAMES. The owner, 2026-10-20: "Is there a way to make the street names on the map more clear? they
 * seem to disappear over the colored lanes". The base map's road names (@protomaps/basemaps `roads_labels_major`
 * and `roads_labels_minor`) are already drawn over the stress lines (lib/mapGlue.ts, addStressOverlay), but as
 * light grey (#938a8d, 3.4:1 on white) 12 px Regular with a 1 px halo, which a 5-6.5 px coloured line shows
 * through. Here they are 15 px (the owner, 2026-10-20: "a point or two up" on 13) in Atkinson Hyperlegible Next
 * SemiBold (the owner's pick, 2026-10-20; bundled, lib/mapGlyphs.ts), dark grey (9.1:1 on the white halo; near-black,
 * 17:1, with the accessibility switch) on a 3.5 px white halo (3.75 px with the switch, the most MapLibre draws at
 * 15 px), so each name sits on its own white band over any line. The names are on the canvas, out of a screen
 * reader's reach as before; the road panel says a road's name in words.
 */
export const ROAD_LABEL_LAYER_IDS = ["roads_labels_major", "roads_labels_minor"];
export const ROAD_LABEL = {
  // Bundled with the app, not the base map (lib/mapGlyphs.ts, MAP_LABEL_FONT).
  font: "Atkinson Hyperlegible Next SemiBold",
  size: 15,
  /** In a ride, at either text size (the owner, 2026-10-20: "20 pt for road names regardless of size choice for ride mode";
   *  "When riding you want to be able to see quickly"). */
  rideSize: 20,
  color: "#4d4749",
  strongColor: "#1c1a1b",
  halo: "#ffffff",
  haloWidth: 3.5,
  strongHaloWidth: 3.75,
  haloBlur: 0,
};

// A ride's street names shortened as on the cue card (lib/cueShown.ts, shortStreets): "R Street Northwest" as "R St NW"
// (the owner, 2026-10-20: fewer words, larger text). A style expression has no regex, so only a trailing quadrant and
// the street type before it (or at the end) are shortened, as the cue card does; the name is the English one, else the
// local one; a name in another script keeps the base map's own field.
const RIDE_QUADRANTS = [["Northwest", "NW"], ["Northeast", "NE"], ["Southwest", "SW"], ["Southeast", "SE"]];
const RIDE_TYPES = [
  ["Avenue", "Ave"], ["Street", "St"], ["Road", "Rd"], ["Boulevard", "Blvd"], ["Drive", "Dr"], ["Parkway", "Pkwy"],
  ["Place", "Pl"], ["Terrace", "Ter"], ["Lane", "Ln"], ["Court", "Ct"], ["Trail", "Trl"], ["Highway", "Hwy"],
  ["Circle", "Cir"], ["Square", "Sq"], ["Bridge", "Br"],
];
const endsWith = (v, tail, more = 0) => [
  "all",
  [">=", ["length", v], tail.length + more],
  ["==", ["slice", v, ["-", ["length", v], tail.length]], tail],
];
const cut = (v, n) => ["slice", v, 0, ["-", ["length", v], n]];
/**
 * @param {unknown} [base] the base map's own text-field, for names in another script
 * @param {unknown} [name] the name to shorten: the base map's English name, else its local one (a trail's is its own)
 */
export function rideRoadLabelField(base = null, name = ["coalesce", ["get", "name:en"], ["get", "pgf:name"], ["get", "name"], ""]) {
  const n = ["var", "n"];
  const q = ["var", "q"];
  const b = ["var", "b"];
  const short = [
    "let",
    "n",
    name,
    [
      "let",
      "q",
      [
        "case",
        ...RIDE_QUADRANTS.flatMap(([long, short]) => [endsWith(n, ` ${long}`, 1), ` ${short}`, endsWith(n, ` ${short}`, 1), ` ${short}`]),
        "",
      ],
      [
        "let",
        "b",
        // Every quadrant word is 9 letters, so " Northwest" and the rest are 10 characters to cut; " NW" and the rest 3.
        ["case", ["==", q, ""], n, ["==", ["slice", n, ["-", ["length", n], 3]], q], cut(n, 3), cut(n, 10)],
        [
          "concat",
          ["case", ...RIDE_TYPES.flatMap(([long, short]) => [endsWith(b, ` ${long}`, 1), ["concat", cut(b, long.length), short]]), b],
          q,
        ],
      ],
    ],
  ];
  // A name in another script, with no English one, keeps the base map's own field and its fonts (Atkinson has no glyphs for it).
  return base === null ? short : ["case", ["all", ["!", ["has", "name:en"]], ["has", "script"]], base, short];
}

/** The street names' paint, plain or with the accessibility switch on. A path's name (the base map's `path` kind,
 *  named from zoom 15) is in the trail names' purple (TRAIL_LABEL), so a trail reads as one at every zoom. */
export function roadLabelPaint(strong = accessibilityOn()) {
  const street = strong ? ROAD_LABEL.strongColor : ROAD_LABEL.color;
  return {
    "text-color": ["case", ["==", ["get", "kind"], "path"], strong ? TRAIL_LABEL.strongColor : TRAIL_LABEL.color, street],
    "text-halo-color": ROAD_LABEL.halo,
    "text-halo-width": strong ? ROAD_LABEL.strongHaloWidth : ROAD_LABEL.haloWidth,
    "text-halo-blur": ROAD_LABEL.haloBlur,
  };
}

/**
 * THE NEIGHBOURHOOD AND TOWN NAMES. The owner, 2026-10-21, of the base map's thin, spaced grey capitals ("GLEN
 * HAVEN", "SLIGO WOODS") and its light town names ("Kemp Mill Estates"): "Make the neighborhood names also in bold
 * an with the same font so they are readable. Cities too."; then, "Maybe change the font yo a bolder one from the
 * same family or use small caps so it stands out". The base map's `places_subplace` (neighbourhoods) and
 * `places_locality` (cities and towns) are drawn here in the street names' family at a heavier weight (Atkinson
 * Hyperlegible Next ExtraBold, bundled, lib/mapGlyphs.ts), dark on the street names' white halo. A town is in mixed
 * case; a neighbourhood in capitals at a smaller size with a little spacing (MapLibre has no true small caps), so it
 * reads apart from a street name and below a town. A town reads above a neighbourhood (larger, darker), and both stay
 * under the station names' 18 px (v0.11.0, lib/railLayer.ts), the key wayfinders. A neighbourhood is 11 px at zoom
 * 12, 13 px at 14, 14 px from 17; a town 13 px at zoom 8, 15 px at 11, 16 at 14, 17 from 17; a large one (the base
 * map's population_rank 9 or more: Silver Spring, Wheaton) 15 px at 8 and 17 px from 11, as the base map draws it
 * larger too. The sizes do not change in a ride (the
 * street names are what a rider reads there).
 * Only the style changes: the names, their filters and their placement are the base map's.
 */
export const PLACE_LABEL_LAYER_IDS = ["places_subplace", "places_locality"];
export const PLACE_LABEL = {
  font: "Atkinson Hyperlegible Next ExtraBold",
  neighbourhood: {
    size: ["interpolate", ["linear"], ["zoom"], 12, 11, 14, 13, 17, 14],
    transform: "uppercase",
    letterSpacing: 0.04,
    color: "#5c5658",
    strongColor: "#1c1a1b",
  },
  town: {
    transform: "none",
    letterSpacing: 0,
    size: ["interpolate", ["linear"], ["zoom"], 8, 13, 11, 15, 14, 16, 17, 17],
    /** A large town's (population_rank LARGE_TOWN_RANK or more). */
    largeSize: ["interpolate", ["linear"], ["zoom"], 8, 15, 11, 17],
    color: "#2e2a2b",
    strongColor: "#000000",
  },
  largeTownRank: 9,
  halo: "#ffffff",
  haloWidth: 2.5,
  strongHaloWidth: 2.75,
};

/**
 * A town's size: its ramp, or a large town's. MapLibre allows one zoom ramp, at the top, so the rank is a case at
 * each zoom of the two ramps' stops together, each ramp read there as MapLibre reads it (linear between stops).
 */
export function townLabelSize(town, largeTownRank) {
  const ramp = (size) => size.slice(3);
  const at = (stops, zoom) => {
    if (zoom <= stops[0]) return stops[1];
    for (let k = 2; k < stops.length; k += 2) if (zoom <= stops[k]) return stops[k - 1] + ((stops[k + 1] - stops[k - 1]) * (zoom - stops[k - 2])) / (stops[k] - stops[k - 2]);
    return stops[stops.length - 1];
  };
  const small = ramp(town.size);
  const large = ramp(town.largeSize);
  const zooms = [...new Set([...small, ...large].filter((_, k) => k % 2 === 0))].sort((a, b) => a - b);
  const isLarge = [">=", ["coalesce", ["get", "population_rank"], 0], largeTownRank];
  return ["interpolate", ["linear"], ["zoom"], ...zooms.flatMap((zoom) => [zoom, ["case", isLarge, at(large, zoom), at(small, zoom)]])];
}

/** A place name layer's paint (PLACE_LABEL), plain or with the accessibility switch on. */
export function placeLabelPaint(id, strong = accessibilityOn()) {
  const kind = id === "places_locality" ? PLACE_LABEL.town : PLACE_LABEL.neighbourhood;
  return {
    "text-color": strong ? kind.strongColor : kind.color,
    "text-halo-color": PLACE_LABEL.halo,
    "text-halo-width": strong ? PLACE_LABEL.strongHaloWidth : PLACE_LABEL.haloWidth,
    "text-halo-blur": 0,
  };
}

/**
 * THE BASE MAP'S OTHER LABELS. The owner, 2026-10-21, of the labels the base map still drew small, light and thin:
 * "All into stret name style. See if it gets too crowded." Park and place names (`pois`), water names (rivers and
 * streams, lakes, the bay), islands and house numbers are drawn in the street names' face (Atkinson Hyperlegible
 * Next SemiBold) on their white halo, each in a dark shade of the colour the base map gives it, 7:1 or more on the
 * halo, so a park still reads green and a creek blue. Place names are the street names' 15 px; house numbers, one
 * on every house at zoom 18, 13 px so they do not crowd each other out; the base map's italics and letter spacing go.
 * The route numbers in their shields are 12 px (the base map's 8) with the shield drawn 1.5 times as large (1.2 for
 * its 0.8), so the number still fits it. The names, filters and zooms are the base map's own.
 */
export const OTHER_LABEL = {
  font: ROAD_LABEL.font,
  size: ROAD_LABEL.size,
  addressSize: 13,
  halo: "#ffffff",
  haloWidth: ROAD_LABEL.haloWidth,
  addressHaloWidth: 3,
  /** The base map's colour for a kind of place, darkened: green parks, blue transit, violet public places, teal shops, brown food, plum sights; any other kind grey. */
  poiColors: [
    [["beach", "forest", "marina", "park", "peak", "zoo", "garden", "bench"], "#166534"],
    [["aerodrome", "station", "bus_stop", "ferry_terminal"], "#1e40af"],
    [["stadium", "university", "library", "school", "animal", "toilets", "drinking_water", "post_office", "building", "townhall"], "#4b3f72"],
    [["supermarket", "convenience", "books", "beauty", "electronics", "clothes"], "#0c4a6e"],
    [["restaurant", "fast_food", "cafe", "bar"], "#7c2d12"],
    [["attraction", "museum", "theatre", "artwork"], "#831843"],
  ],
  poiOther: ROAD_LABEL.color,
  water: "#1e3a8a",
  island: ROAD_LABEL.color,
  address: "#57534e",
  shield: { size: 12, iconSize: 1.2, color: "#2e2a2b" },
};
/**
 * THE MOTORWAYS' NAMES. The owner, 2026-10-21: "Seeing the map zoomed out, having those huge highway names are silly,
 * bikes don't use highways. Only show when zoomed further in." A motorway (the base map's road kind "highway": OSM's
 * motorway and motorway_link, the interstates; a trunk road such as a parkway is a "major_road") is named, and its route shield drawn, only from HIGHWAY_LABEL_MIN_ZOOM,
 * the zoom every road is drawn solid at, where a rider can need it as a landmark beside a street. Every other road's
 * name and shield (a US or state route on a major or trunk road, which a rider may use) is as the base map has it.
 */
export const HIGHWAY_LABEL_MIN_ZOOM = 14;
const notMotorwayYet = ["any", ["!=", ["get", "kind"], "highway"], [">=", ["zoom"], HIGHWAY_LABEL_MIN_ZOOM]];
/** A base map road-label layer's filter, its motorways left out below HIGHWAY_LABEL_MIN_ZOOM. */
function laterMotorways(filter) {
  // The base map writes roads_labels_major's in the legacy form, ["in", "kind", ...], which cannot sit in an expression.
  const expression = Array.isArray(filter) && filter[0] === "in" && typeof filter[1] === "string"
    ? ["in", ["get", filter[1]], ["literal", filter.slice(2)]]
    : filter;
  return ["all", expression, notMotorwayYet];
}

export const OTHER_LABEL_LAYER_IDS = ["pois", "water_waterway_label", "water_label_ocean", "water_label_lakes", "earth_label_islands", "address_label", "roads_shields"];

/** One of the base map's other label layers (OTHER_LABEL) as this app draws it. */
function clearOtherLabel(layer) {
  const L = OTHER_LABEL;
  const named = (color, size = L.size, halo = L.haloWidth) => ({
    ...layer,
    layout: { ...layer.layout, "text-font": [L.font], "text-size": size, "text-letter-spacing": 0 },
    paint: { ...layer.paint, "text-color": color, "text-halo-color": L.halo, "text-halo-width": halo, "text-halo-blur": 0 },
  });
  switch (layer.id) {
    case "pois":
      return named(["case", ...L.poiColors.flatMap(([kinds, color]) => [["in", ["get", "kind"], ["literal", kinds]], color]), L.poiOther]);
    case "earth_label_islands":
      return named(L.island);
    case "address_label":
      return named(L.address, L.addressSize, L.addressHaloWidth);
    case "roads_shields":
      return {
        ...layer,
        filter: laterMotorways(layer.filter),
        layout: { ...layer.layout, "text-font": [L.font], "text-size": L.shield.size, "icon-size": L.shield.iconSize },
        paint: { ...layer.paint, "text-color": L.shield.color },
      };
    default:
      return named(L.water);
  }
}

/** The base map's layers with the street names (ROAD_LABEL), place names (PLACE_LABEL) and other labels (OTHER_LABEL) restyled; every other layer as given. */
export function withClearRoadLabels(layers, strong = accessibilityOn()) {
  return layers.map((layer) => {
    if (ROAD_LABEL_LAYER_IDS.includes(layer.id)) {
      return {
        ...layer,
        ...(layer.id === "roads_labels_major" ? { filter: laterMotorways(layer.filter) } : {}),
        layout: { ...layer.layout, "text-font": [ROAD_LABEL.font], "text-size": ROAD_LABEL.size },
        paint: { ...layer.paint, ...roadLabelPaint(strong) },
      };
    }
    if (PLACE_LABEL_LAYER_IDS.includes(layer.id)) {
      const { town, neighbourhood, largeTownRank } = PLACE_LABEL;
      const kind = layer.id === "places_locality" ? town : neighbourhood;
      const size = kind === town ? townLabelSize(town, largeTownRank) : neighbourhood.size;
      return {
        ...layer,
        layout: { ...layer.layout, "text-font": [PLACE_LABEL.font], "text-size": size, "text-transform": kind.transform, "text-letter-spacing": kind.letterSpacing },
        paint: { ...layer.paint, ...placeLabelPaint(layer.id, strong) },
      };
    }
    if (OTHER_LABEL_LAYER_IDS.includes(layer.id)) return clearOtherLabel(layer);
    return layer;
  });
}

/**
 * THE MAJOR TRAILS' NAMES. The owner, 2026-10-21: "Major off road bike trails like the Metropolitan Branch Trail
 * should be named on the map." The tiles carry `trail_name` on the long trails the zoomed-out map keeps (a path on
 * a regional-or-larger bicycle route or a long walking route, or in a named run of 2.5 mi or more, 5 mi unpaved;
 * core/stress_tiles.py, trail_name_rule), so "major" is the rule the map already draws by, not a list. The name is
 * drawn along the line from TRAIL_LABEL_MIN_ZOOM, the zoom the station names and every street come in at, in the
 * street names' face, size and white halo (ROAD_LABEL; 20 px and shortened in a ride, as they are) but in the
 * purple of the off-road path's rails (FACILITIES, `path`): 10.9:1 on the halo, near-black purple (15.2:1) with the
 * accessibility switch. The layer is under the base map's labels, so a street name or a station's wins a place
 * both want; and the climbs go under it (MapView). From zoom 15 the base map names every path too, in the same
 * purple (roadLabelPaint). The name is on the canvas, out of a screen reader's reach; the road panel says it.
 */
export const TRAIL_LABEL_LAYER_ID = "trail-name";
export const TRAIL_LABEL_MIN_ZOOM = 12;
export const TRAIL_LABEL = {
  color: "#4c1d95",
  strongColor: "#2e1065",
  // MapLibre's own spacing, so a name finds a place between the street and station names; a gentle bend at most, so it reads.
  spacing: 250,
  maxAngle: 30,
  padding: 6,
};

/** The trail names' paint, plain or with the accessibility switch on. */
export function trailLabelPaint(strong = accessibilityOn()) {
  return {
    "text-color": strong ? TRAIL_LABEL.strongColor : TRAIL_LABEL.color,
    "text-halo-color": ROAD_LABEL.halo,
    "text-halo-width": strong ? ROAD_LABEL.strongHaloWidth : ROAD_LABEL.haloWidth,
    "text-halo-blur": ROAD_LABEL.haloBlur,
  };
}

/** A ride's trail names: shortened as the street names are ("Rock Creek Trl"). */
export function rideTrailLabelField() {
  return rideRoadLabelField(null, ["get", "trail_name"]);
}

/** The trail names' layer (2026-10-21): along each major trail, from zoom 12. */
export function trailLabelLayers(sourceId = "stress", when = DEFAULT_WHEN, strong = accessibilityOn()) {
  return [
    {
      id: TRAIL_LABEL_LAYER_ID,
      type: "symbol",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      minzoom: TRAIL_LABEL_MIN_ZOOM,
      filter: stressFilters(when)[TRAIL_LABEL_LAYER_ID],
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": TRAIL_LABEL.spacing,
        "text-field": ["get", "trail_name"],
        "text-font": [ROAD_LABEL.font],
        "text-size": ROAD_LABEL.size,
        "text-max-angle": TRAIL_LABEL.maxAngle,
        "text-padding": TRAIL_LABEL.padding,
      },
      paint: trailLabelPaint(strong),
    },
  ];
}

// The stress tiles' layer and property, per the SHARED API CONTRACT for
// /tiles/stress/{z}/{x}/{y}.pbf: one layer named "stress", a "tier" of 1-5 or
// null on each feature (5 is "legal but avoid", added 2026-09-27).
export const STRESS_TILE_LAYER = "stress";

/**
 * Roads closed to motor traffic at set times (the tiles' "car_free", or
 * "car_free_only" in a zoomed-out tile, which carries such a road for those
 * times alone: core/stress_tiles.py). The owner, 2026-09-29: "One note:
 * Car-free roads should be regarded the same as an off-road path on a map."
 * and, for the weekend closures, "Path on weekends only" - so in one of those
 * ride times the road draws exactly as an off-road path, tier 1, and in any
 * other with its own stress, and a zoomed-out tile's road is not drawn then.
 * A road closed for good is a path in the tiles already. `when` is the ride
 * time the map follows: "weekend", "weekday_rush", "weekday_offpeak" or "night".
 */
const carFreeNow = (when) => [
  "in",
  when,
  ["coalesce", ["get", "car_free"], ["get", "car_free_only"], ""],
];

/** The tier a feature draws at in the ride time `when`. */
export const tierAt = (when) => ["case", carFreeNow(when), 1, ["get", "tier"]];

/** The bike facility a feature draws as in the ride time `when`. */
export const facilityAt = (when) => ["case", carFreeNow(when), "path", ["get", "facility"]];

/** Whether a feature is drawn at all in the ride time `when`. */
export const drawnAt = (when) => [
  "any",
  ["!", ["has", "car_free_only"]],
  ["in", when, ["get", "car_free_only"]],
];

/** Until the map knows the ride time; App gives it at once (lib/rideTime.ts). */
export const DEFAULT_WHEN = "weekday_offpeak";

/** A road whose bike facility is mapped as a way of its own beside it (the tiles' "separate_bikeway"). */
const besideBikeway = ["==", ["get", "separate_bikeway"], true];

/**
 * The busy roads - LTS 3, LTS 4 and Avoid - are background.
 * The owner, 2026-09-29: "The high LTS roads aren't that important because you
 * aren't going to route around them." - "Show them faintly" (OWNER-DECISIONS
 * 76) - then "Make solid at 14" (77): faint at z12-13, where the tiles first
 * carry them, and solid from SOLID_MIN_ZOOM. One beside a separately mapped
 * bike facility (15th Street NW beside its cycle track) is not drawn until
 * BESIDE_ROAD_MIN_ZOOM and then faint at every zoom, so the facility is the
 * main line: "In that case, don't show the road, perhaps hide it until zoom
 * 15-16. The bike lane should show up as the main." (73) and "Keep it faint if
 * it parallels a protected bike path." (78). 15 of the owner's 15-16: at 15 a
 * street and its cycle track are 10-15 px apart on screen, room for both.
 */
export const BUSY_MIN_TIER = 3;
export const SOLID_MIN_ZOOM = 14;
export const BESIDE_ROAD_MIN_ZOOM = 15;

/**
 * THE ZOOMED-OUT WIDTHS (OWNER-DECISIONS 375, 2026-10-04: "Also zoomed out, can we
 * stick to mostly the longer trails, it's getting messy."). At z10 and z11 a path
 * was drawn at its full width (2.5 px, a 2 px casing, and path rails 2.5 px each
 * side: 9.5 px a line), which is what turned Columbia's pathways into solid
 * blobs. Below FULL_WIDTH_MIN_ZOOM (12, `STRESS_ZOOMS.quiet`, which a test holds
 * equal) the line and the rails are scaled, each by its own factor at z10 and at
 * z11, so a long trail reads as a line and not a ribbon (a path is 5.4 px at
 * z10, 6.9 px at z11). The casing's edge is not thinned (scale 1): it is a pixel
 * a side, a pixel and a half with the accessibility switch, because on a line
 * with no rails (an unpaved trail, a car-free road) it is the only thing 3:1
 * against the base map (accessibility review SF2 of ZOOMED-TRAILS; the
 * orchestrator's call, at a pixel more than the 4.4 px first drawn). The colours
 * are not touched: the two-tone palette and the brown unpaved ramp keep their
 * line and casing colours. What a low-vision rider sees stays: a line of 1.25 px
 * or more, a casing edge and a rail of a pixel or more, and an unpaved mark of a
 * pixel or more (ZOOMED_OUT_MIN_PX). The accessibility switch's extra width is
 * scaled with the line, so its line and edge stay wider than the default's at
 * every zoom. ZOOMED_OUT_NEAR_ZOOM is where the server's z11 level starts
 * (`core.stress_tiles.TRAILS_NEAR_MIN_ZOOM`, which a test holds equal).
 */
export const FULL_WIDTH_MIN_ZOOM = 12;
export const ZOOMED_OUT_NEAR_ZOOM = 11;
export const ZOOMED_OUT_SCALE = {
  10: { line: 0.55, casing: 1, rail: 0.4 },
  [ZOOMED_OUT_NEAR_ZOOM]: { line: 0.75, casing: 1, rail: 0.6 },
};
/** The narrowest an edge, a rail or the unpaved mark is drawn zoomed out. */
export const ZOOMED_OUT_MIN_PX = 1;
/** The zoom `step` stops for the zoomed-out grades, ahead of the full widths. */
function zoomedOutStops(at) {
  return [at(10), ZOOMED_OUT_NEAR_ZOOM, at(ZOOMED_OUT_NEAR_ZOOM), FULL_WIDTH_MIN_ZOOM];
}

/**
 * `opacity` and `widthScale` keep the line faint, as the owner chose. A faint
 * line alone is 1.1-2.6:1 against the earth (the amber, the red and the dark
 * red of the busy tiers, blended 40% into it), under WCAG 1.4.11's 3:1 for a
 * graphic a rider needs, so it also carries a second cue that does not depend
 * on its colour: a thin dark edge (`edgePx` wide each side, `edgeOpacity` of
 * `edge`, or of the tier's own casing when that is dark), drawn as a ring
 * around the line (line-gap-width) rather than as a band under it, so the
 * tier's colour inside it is not muddied. 60% of a near black is at least
 * 3.7:1 on every surface of the base map (stressContrast.test.ts); the trade
 * is that a faint road reads as a hairline outline, not as nothing, and is not
 * the heavy line it becomes at SOLID_MIN_ZOOM. No tier's line alone reaches
 * 3:1 at 40% (1.1:1 to 2.6:1 on the earth); only a darker or heavier line
 * would, which is what the owner asked it not to be.
 */
export const FAINT = { opacity: 0.4, widthScale: 0.6, edge: "#1c1917", edgeOpacity: 0.65, edgePx: 1 };

/** The colour of a tier's faint edge: its casing when that is a near-black, else FAINT.edge (Avoid's red casing is not dark enough to be an edge). */
export function faintEdgeColour(tier) {
  return relativeLuminance(tier.casing) < DARK_CASING_LUMINANCE ? tier.casing : FAINT.edge;
}

/** An alley (the tiles' "alley"). */
const isAlley = ["==", ["get", "alley"], true];

/**
 * Alleys draw only from ALLEY_MIN_ZOOM, faint, as context: "Alley cut
 * throughs should only be used if the roads are very problematic nearby. Cut
 * down on showing them, and only use them if nessicary. Because people don't
 * think of these as intersections, alley dodging is dangerous." (the owner,
 * 2026-09-29; OWNER-DECISIONS 100). 16: close enough that an alley reads as
 * the lane behind the houses it is, not as a street.
 */
export const ALLEY_MIN_ZOOM = 16;

/**
 * A line's `full` value (opacity or width) by zoom: an alley not drawn below
 * ALLEY_MIN_ZOOM and faint from it; a busy road faint, or not drawn, where the
 * rules above say; any other line as it is.
 */
function byZoom(full, faint, busy, hidden = 0, zoomedOut = null) {
  const at = (zoom) => {
    const alley = zoom >= ALLEY_MIN_ZOOM ? faint : hidden;
    const road = !busy
      ? full
      : ["case", besideBikeway, zoom >= BESIDE_ROAD_MIN_ZOOM ? faint : hidden, zoom >= SOLID_MIN_ZOOM ? full : faint];
    return ["case", isAlley, alley, road];
  };
  // The zoomed-out grades (ZOOMED_OUT_SCALE): `zoomedOut(zoom)` is the value at
  // z10 or z11, ahead of the full-width steps. Only for a line that is not a
  // busy road, which the tiles do not carry there.
  const out = zoomedOut && !busy ? zoomedOutStops(zoomedOut) : [];
  // A plain street at z12 and z13 (STREET_THIN_SCALE): thinner, so a city grid is a mesh and not a carpet.
  const street = (zoom) => (out.length ? ["case", isPlainStreet, zoomedOut(zoom), at(zoom)] : at(zoom));
  return [
    "step",
    ["zoom"],
    ...out,
    street(FULL_WIDTH_MIN_ZOOM),
    STREET_THIN_LAST_ZOOM,
    street(STREET_THIN_LAST_ZOOM),
    SOLID_MIN_ZOOM,
    at(SOLID_MIN_ZOOM),
    BESIDE_ROAD_MIN_ZOOM,
    at(BESIDE_ROAD_MIN_ZOOM),
    ALLEY_MIN_ZOOM,
    at(ALLEY_MIN_ZOOM),
  ];
}

/**
 * THE CITY GRID AT Z12-13. The owner, 2026-10-21: "lts colored roads look very crowded at the nax zoom they show up
 * in urban areas, but it's needed for rural ones. So let's also check to make sure the map doesn't look crowded".
 * At z12 a downtown block is 2-3 px on screen, so every street at its full width (2.5-3.25 px and a 2 px casing)
 * filled the grid with colour. A plain street (no bike facility, not a trail, paved, open to cars) is drawn
 * thinner at z12 and z13, `line` and `casing` scaling its line and its casing's extra; a bike lane, a path, a trail,
 * an unpaved road and a car-free street keep their widths, so they stand out of the grid as the ways a rider
 * looks for. Only a street the tiles mark `dense` (a city grid) is thinned; a rural road keeps its full width, as
 * does every street in a tile drawn before the server marked them.
 * The busy roads are faint there already (FAINT). From SOLID_MIN_ZOOM (14) every line is its full width. The
 * casing's dark edge thins with the line (half a pixel a side at z12), which is what lifts the grid's dark mesh;
 * with the accessibility switch on it stays a full pixel a side, as on the zoomed-out trails (ZOOMED_OUT_MIN_PX).
 */
export const STREET_THIN_SCALE = {
  [FULL_WIDTH_MIN_ZOOM]: { line: 0.4, casing: 0.5 },
  13: { line: 0.6, casing: 0.75 },
};
const STREET_THIN_LAST_ZOOM = 13;
const isPlainStreet = [
  "all",
  // In a dense street grid: the tiles mark a z12-13 street `dense` where its neighbourhood is a city grid
  // (core/stress_tiles.py), so a rural road keeps its full width (the owner, 2026-10-21: "City only").
  ["==", ["get", "dense"], true],
  // The tiles carry `facility` "none" on a street with none (the column's default), and none at all on an older table.
  ["match", ["coalesce", ["get", "facility"], "none"], "none", true, false],
  ["!=", ["get", "trail"], true],
  ["!=", ["get", "unpaved"], true],
  ["!", ["has", "car_free"]],
  ["!", ["has", "car_free_only"]],
  ["!=", ["get", "alley"], true],
];

/** A zoom's scale: ZOOMED_OUT_SCALE at z10 and z11, STREET_THIN_SCALE (plain streets only) at z12 and z13. */
const scaleAt = (zoom) => ZOOMED_OUT_SCALE[zoom] ?? STREET_THIN_SCALE[zoom];

/** The line width a tier is drawn at, z10 or z11 (ZOOMED_OUT_SCALE), or a plain street's at z12 or z13 (STREET_THIN_SCALE). */
export function zoomedOutLine(tier, zoom) {
  return tier.width * scaleAt(zoom).line;
}

/** The casing width at those zooms: the thinned line and the casing's thinned extra. */
export function zoomedOutCasing(tier, zoom) {
  const casing = tier.strong && STREET_THIN_SCALE[zoom] ? 1 : scaleAt(zoom).casing;
  return zoomedOutLine(tier, zoom) + (tier.casingExtra ?? CASING_EXTRA_PX) * casing;
}

/** A line's paint, faint and late as byZoom says. */
function linePaint(color, width, busy, zoomedOut = null) {
  return {
    "line-color": color,
    "line-width": byZoom(width, width * FAINT.widthScale, busy, 0, zoomedOut),
    "line-opacity": byZoom(1, FAINT.opacity, busy),
  };
}

/**
 * Whether the map is the Mass Ride's (OWNER-DECISIONS 325): set by App from the ride type. The
 * stress layers - LTS colours, facility rails, trails and the Avoid style - are not drawn then, at
 * any zoom (417, 417a; lib/mapGlue.ts hides them), and massStyle.js's layers are, from the Mass
 * Ride tiles. Their filters also take out any feature with a capacity (`massHides`).
 */
let massRide = false;

export function massRideOn() {
  return massRide;
}

export function setMassRide(on) {
  massRide = on;
}

/**
 * THE MOUNTAIN-BIKE TRAILS (OWNER-DECISIONS 452, 452a). The stress tiles mark a trail in the
 * mountain-bike class with `mtb` (true, or left out: core/stress_tiles.py, from the segment's
 * `mtb_only`, which `pipeline.trail_closures.MTB_ONLY` writes for `routemaker.trailaccess.MTB`).
 * Routing closes them for every ride type but Gravel and Mountain Goat (the off-road graph).
 * 452 hid them; 452a, the owner: "I want people to know where the trails are, but make them
 * clear that it's not routing." So none of the routable layers (stress, unpaved,
 * surface-unknown, ring, gap, facility) draws one (`mtbHides`), and they have a look of their
 * own instead (`mtbTrailLayers`, MTB_TRAIL): first a thin mid-grey line of fine dots with no casing; since
 * v0.6.0 (the owner, 2026-10-12: "Mountain bike trails seem plotted but don't show up very well") a 3 px
 * line on a white edge (MTB_HALO) with short dark cross-ticks outside it (MTB_TICKS), grey dashes for an unrated
 * trail, no rails and no stress colour, under every routable layer, from MTB_MIN_ZOOM (the zoom the tiles carry
 * them from, as before). The ticks carry the meaning, not the colour: every routable line's casing and ring is
 * solid, in every palette. In the Mountain Bike ride type the trails up to the rider's level draw as routable
 * (slice 6) and only the harder ones in this look. This supersedes 290(b)'s "draw them
 * faint" (FOLLOWUP-MTB-FAINT). Since 454 the line is an optional map layer, off until the rider
 * turns it on (mtbTrailsOn, below; lib/mapGlue.ts overlayLayerShown). Not the tiles' `rough`: that is a rough surface (`is_rough`,
 * paved cobbles among them, 440), not this class: an unpaved rough way draws brown and any other unpaved one gravel grey
 * (GRAVEL_PALETTES), whether or not it is a mountain-bike trail.
 *
 * MTB_TRAILS_ROUTABLE is the switch for a future mountain-bike mode: true draws them as any
 * other trail, in the routable layers, and the not-for-routes layer draws nothing (and the
 * legend drops its row, lib/stressLegend.ts). Such a mode would pass `routableMtb` to
 * stressFilters rather than flip this for every ride type.
 */
export const MTB_TRAILS_ROUTABLE = false;

/**
 * The Mountain Bike ride type (docs/MTB-TOPO-PLAN.md, slice 6) is that mode. Its graph opens every
 * mountain-bike trail a bicycle may use, and the rider chooses the hardest level (1 to 4) the plan
 * may use, so `routableMtb` may also be that level: the trails at or below it (an unrated one
 * counted as level 2, `mtbWithin`) draw in the routable layers, as any other trail, and the harder
 * ones keep the not-for-routes look of their level. Set by App from the ride type and the level;
 * null on every other ride type. MapView sets the filters again in place when it changes.
 */
let routableMtb = null;
const routableMtbListeners = new Set();

/** The level the routable layers draw mountain-bike trails up to, or null (not the Mountain Bike ride type). */
export function routableMtbLevel() {
  return routableMtb;
}

export function setRoutableMtb(level) {
  const next = Number.isInteger(level) && level >= 1 && level <= 4 ? level : null;
  if (routableMtb === next) return;
  routableMtb = next;
  routableMtbListeners.forEach((listener) => listener());
}

export function subscribeRoutableMtb(listener) {
  routableMtbListeners.add(listener);
  return () => {
    routableMtbListeners.delete(listener);
  };
}

/** An unrated mountain-bike trail counts as this level (`routemaker.mtbmode.UNRATED_LEVEL`). */
export const MTB_UNRATED_LEVEL = 2;

/** A mountain-bike trail at or below `level`: its `mtb_level`, an unrated one as MTB_UNRATED_LEVEL. */
export function mtbWithin(level) {
  return ["<=", ["coalesce", ["get", "mtb_level"], MTB_UNRATED_LEVEL], level];
}

/** The filter that takes the mountain-bike trails (the tiles' `mtb`) out of a routable layer. */
export const mtbHides = ["!=", ["get", "mtb"], true];

/** A mountain-bike trail (the tiles' `mtb`). */
export const isMtbTrail = ["==", ["get", "mtb"], true];

/**
 * The unrated trails' look: a brown dashed line (until 2026-10-21 mid-grey, #5f6368; `dash`, in line widths: a dash one and a half
 * widths long, then a gap as long) on the white edge every mountain-bike trail has (MTB_HALO).
 * Until v0.6.0 this was a 1.5 px line of fine dots with no edge, which the owner could hardly
 * see (2026-10-12: "Mountain bike trails seem plotted but don't show up very well"); it is now as
 * wide as a level's line. #5f6368 is 3.5:1 or more from every surface of the light base map (the
 * lowest, scrub's green, 3.54:1; parks' 3.57:1; white roads 6.05:1; mtbTrail.test.ts holds 3:1)
 * and 6.05:1 on its white edge, and it is not a stress colour in any palette. With the
 * accessibility switch on (`strong`) the line is wider and darker (#4b5260, the panels' muted
 * text, 4.59:1 or more). The legend's swatch draws it on the base map's earth colour
 * (`legendGround`), so it reads as on the map in a dark panel too.
 */
export const MTB_TRAIL = {
  // Brown since 2026-10-21 (GRAVEL_PALETTES: "natural surface trails brown and gravel grey"): a dirt trail is brown
  // like every natural surface, and no longer the grey of a gravel path. Darker with the switch.
  color: "#7a5536",
  strongColor: "#5e3f26",
  width: 3,
  strongWidth: 4,
  dash: [1.5, 1.5],
  legendGround: "#e2dfda",
};

/**
 * The white edge under every mountain-bike trail's line (v0.6.0, the owner's report of 2026-10-12): `px` each
 * side of the line, `strongPx` with the accessibility switch. It lifts the line off park green, woods and the
 * contour lines. Every line colour is 4.5:1 or more against it (mtbLevels.test.ts). A white edge alone is not the
 * not-for-routes mark: LTS 4's casing is white in the default and accessible palettes.
 */
export const MTB_HALO = { color: "#ffffff", px: 1.5, strongPx: 2 };

/** The white edge's width under a line `width` px wide, plain or with the accessibility switch. */
function mtbHaloWidth(width, strong) {
  return width + 2 * (strong ? MTB_HALO.strongPx : MTB_HALO.px);
}

/**
 * The not-for-routes mark every mountain-bike trail shares (452a: "clearly unlike any routable trail or road"):
 * short dark cross-ticks under the white edge, `px` past it a side (`strongPx` with the accessibility switch), in
 * `dash` (in the ticks' own widths: about a 2 px tick every 12 px). Every stress tier's casing is a solid line, in
 * every palette, so a ticked outer edge is a look no routable line has (mtbLevels.test.ts). One layer
 * (`mtb-trail-ticks`) under every edge: the unrated line and every level's are the same width.
 */
export const MTB_TICKS = { color: "#1c1917", px: 2, strongPx: 2.5, dash: [0.2, 1] };
export const MTB_TICKS_LAYER_ID = "mtb-trail-ticks";

/** The ticks' paint, plain or with the accessibility switch: as wide as the white edge and `px` more a side. */
export function mtbTicksPaint(strong = accessibilityOn()) {
  const width = strong ? MTB_LEVEL.strongWidth : MTB_LEVEL.width;
  return { "line-color": MTB_TICKS.color, "line-width": mtbHaloWidth(width, strong) + 2 * (strong ? MTB_TICKS.strongPx : MTB_TICKS.px), "line-dasharray": MTB_TICKS.dash };
}

/** The zoom the not-for-routes line draws from: where the tiles carry the trails (STRESS_ZOOMS.quiet, held equal by a test; the plan: "MTB trails from zoom 12-13"). */
export const MTB_MIN_ZOOM = 12;

/** The unrated trails' line: colour, width and dashes, plain or with the accessibility switch on. */
export function mtbTrailPaint(strong = accessibilityOn()) {
  return {
    "line-color": strong ? MTB_TRAIL.strongColor : MTB_TRAIL.color,
    "line-width": strong ? MTB_TRAIL.strongWidth : MTB_TRAIL.width,
    "line-dasharray": MTB_TRAIL.dash,
  };
}

/** The unrated trails' white edge (MTB_HALO), solid, under the line. */
export function mtbTrailHaloPaint(strong = accessibilityOn()) {
  const width = strong ? MTB_TRAIL.strongWidth : MTB_TRAIL.width;
  return { "line-color": MTB_HALO.color, "line-width": mtbHaloWidth(width, strong) };
}

/** The not-for-routes layer's id: since 456 the unrated mountain-bike trails' grey dashes; and their white edge. */
export const MTB_TRAIL_LAYER_ID = "mtb-trail";
export const MTB_TRAIL_CASING_LAYER_ID = "mtb-trail-casing";

/**
 * THE MOUNTAIN-BIKE LEVELS (OWNER-DECISIONS 456, 456a-c; docs/MTB-TOPO-PLAN.md, slice 2). The tiles
 * carry a rated mountain-bike trail's difficulty as `mtb_level`, 1 to 4 (core/stress_tiles.py, from
 * `segment.mtb_level`: the higher of `mtb:scale` and `mtb:scale:imba`, S1-S3 to 1-3, S4-S6 to 4; a
 * rating of 0 is a gravel trail and no level, 456b). The mountain-bike layer draws each level in its
 * colour (the owner's starting values: green, blue, black, red), with a pattern of its own (`dash`, in
 * line widths: longer and plainer for the easier levels, more broken for the harder), so the colour is
 * never the only cue; the legend and the road panel name the level in words (`name`,
 * core/segment_info.py MTB_LEVEL_COLOURS, held equal by a test). 452a asks the not-for-routes look to be
 * "clearly unlike any routable trail or road", so every level shares one mark no stress tier has
 * (MTB_TICKS): dark cross-ticks outside a white edge, where every tier's casing and ring is solid. No pattern is the unrated trails' dashes, the unpaved
 * mark, the surface-unknown dashes, a rail's or a tier's (mtbLevels.test.ts). Each colour is 3:1 or
 * more from every surface of the light base map (mtbLevels.test.ts, as MTB_TRAIL's) and 4.5:1 or more
 * on the white edge; the green is #28702c, darker than the starting #2e7d32, which was 3.0009:1 on the
 * base map's scrub (review of slice 2). Until v0.6.0 a level was 2 px over dark cross-ticks, thinner than
 * any tier, and the owner could hardly see them (2026-10-12); a level is now 3 px (4 strong) on its
 * white edge, the ticks outside it, the gaps shorter so the colour reads.
 * An unrated mountain-bike trail keeps grey (`mtb-trail`, MTB_TRAIL; the plan's default), now dashed.
 */
export const MTB_LEVELS = [
  { level: 1, name: "green", color: "#28702c", dash: [6, 1.5], pattern: "long dashes", scale: "S1 or IMBA 1" },
  { level: 2, name: "blue", color: "#1565c0", dash: [3, 1.5], pattern: "short dashes", scale: "S2 or IMBA 2" },
  { level: 3, name: "black", color: "#1c1917", dash: [4, 1.5, 1, 1.5], pattern: "dash-dot", scale: "S3 or IMBA 3" },
  { level: 4, name: "red", color: "#c62828", dash: [4, 1.5, 1, 1.5, 1, 1.5], pattern: "dash-dot-dot", scale: "S4 or above, or IMBA 4 or above" },
];

/**
 * The levels' look, shared by all four: the line's width, plain and with the accessibility switch on
 * (`strong`), in pixels (as wide as the unrated trails' line), drawn on the white edge (MTB_HALO, the
 * "casing" layer); the line's gaps show the white.
 */
export const MTB_LEVEL = { width: 3, strongWidth: 4 };

/** The least gap, in line widths, any level's pattern has (452a: longer than any tier's). */
export const MTB_LEVEL_MIN_GAP = 1.5;

/** A level's layer ids: its line and its casing. */
export const mtbLevelLayerId = (level) => `mtb-level-${level}`;
export const mtbLevelCasingLayerId = (level) => `mtb-level-casing-${level}`;

/**
 * The mountain-bike trail layer's lines (454, 456), bottom first: the shared ticks, every white edge (the unrated
 * trails', then each level's), then every line, so no edge covers another trail's line where two meet.
 */
export const MTB_LINE_LAYER_IDS = [
  MTB_TICKS_LAYER_ID,
  MTB_TRAIL_CASING_LAYER_ID,
  ...MTB_LEVELS.map((l) => mtbLevelCasingLayerId(l.level)),
  MTB_TRAIL_LAYER_ID,
  ...MTB_LEVELS.map((l) => mtbLevelLayerId(l.level)),
];

/**
 * THE MOUNTAIN-BIKE TRAIL NAMES. The owner, 2026-10-10: "Also, for mountain bikes, try to make sure trail names
 * are added in if they are available." The tiles carry an `mtb` trail's name as `name` (core/stress_tiles.py, from
 * `segment.mtb_name`: the OSM `name`, else `mtb:name`, else `ref`; left out where none is mapped). The label layer
 * draws it along the line, from MTB_LABEL_MIN_ZOOM, over every routable line, on this map layer only (it follows
 * the layer's switch with the lines). MapLibre's collision drops a label that would overlap another, and
 * `text-padding` and `symbol-spacing` thin them further; `text-max-angle` is 45 (not the 30 the Mass Ride labels
 * use), so a name still fits along curvy singletrack at z15-16. The text is the line's own colour - its level's, or the
 * unrated trails' grey - on a white halo: each is 4.5:1 or more against the halo (green 6.10:1, blue 5.75:1, black
 * 17.49:1, red 5.62:1, grey 6.05:1; mtbLevels.test.ts), where the base map's path-label grey is not (3.5:1). The
 * name is text a screen reader cannot reach on the canvas; the road panel says it in words (core/segment_info.py).
 */
export const MTB_LABEL_LAYER_ID = "mtb-trail-label";
export const MTB_LABEL_MIN_ZOOM = 15;
// The street names' size and halo (the owner, 2026-10-21: "All into stret name style"); its face is already theirs (lib/mapGlyphs.ts).
export const MTB_LABEL = { font: "Noto Sans Medium", size: 15, halo: "#ffffff", haloWidth: 3.5, padding: 8, spacing: 300, maxAngle: 45 };

/** Every layer of the mountain-bike trail map layer (454): its lines, then its names. */
export const MTB_LAYER_IDS = [...MTB_LINE_LAYER_IDS, MTB_LABEL_LAYER_ID];

/** Whether a layer id is one of the mountain-bike trail layer's (MTB_LAYER_IDS). */
export function isMtbLayerId(id) {
  return MTB_LAYER_IDS.includes(id);
}

/** A level's line and its white edge (the `casing` layer), plain or with the accessibility switch on. */
export function mtbLevelPaint(level, strong = accessibilityOn()) {
  const shape = MTB_LEVELS.find((l) => l.level === level);
  const width = strong ? MTB_LEVEL.strongWidth : MTB_LEVEL.width;
  return {
    line: { "line-color": shape.color, "line-width": width, "line-dasharray": shape.dash },
    casing: { "line-color": MTB_HALO.color, "line-width": mtbHaloWidth(width, strong) },
  };
}

/** The names' text colour: the level's colour, or the unrated trails' grey (darker with the accessibility switch). */
export function mtbLabelColor(strong = accessibilityOn()) {
  return ["match", ["get", "mtb_level"], ...MTB_LEVELS.flatMap((l) => [l.level, l.color]), strong ? MTB_TRAIL.strongColor : MTB_TRAIL.color];
}

/** The names' layer (2026-10-10): along each named mountain-bike trail, from zoom 15, thinned by collision. */
export function mtbLabelLayers(sourceId = "stress", when = DEFAULT_WHEN, strong = accessibilityOn()) {
  return [
    {
      id: MTB_LABEL_LAYER_ID,
      type: "symbol",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      minzoom: MTB_LABEL_MIN_ZOOM,
      filter: stressFilters(when)[MTB_LABEL_LAYER_ID],
      layout: {
        "symbol-placement": "line",
        "symbol-spacing": MTB_LABEL.spacing,
        "text-field": ["get", "name"],
        "text-font": [MTB_LABEL.font],
        "text-size": MTB_LABEL.size,
        "text-max-angle": MTB_LABEL.maxAngle,
        "text-padding": MTB_LABEL.padding,
      },
      paint: { "text-color": mtbLabelColor(strong), "text-halo-color": MTB_LABEL.halo, "text-halo-width": MTB_LABEL.haloWidth },
    },
  ];
}

/**
 * The mountain-bike trail layer (452a, 454, 456): the shared dark ticks, every white edge (the unrated trails', then each level's), then
 * the unrated trails' grey dashes and every level's line. Over the base map's park and land fills and the contour
 * lines (lib/mapGlue.ts adds the overlay under the base map's labels; lib/topoLines.ts puts the contours under its
 * roads), under every routable layer, and the route over all of it.
 */
export function mtbTrailLayers(sourceId = "stress", when = DEFAULT_WHEN, strong = accessibilityOn()) {
  const filters = stressFilters(when);
  const base = { type: "line", source: sourceId, "source-layer": STRESS_TILE_LAYER, minzoom: MTB_MIN_ZOOM };
  return [
    { id: MTB_TICKS_LAYER_ID, ...base, filter: filters[MTB_TICKS_LAYER_ID], paint: mtbTicksPaint(strong) },
    { id: MTB_TRAIL_CASING_LAYER_ID, ...base, filter: filters[MTB_TRAIL_CASING_LAYER_ID], paint: mtbTrailHaloPaint(strong) },
    ...MTB_LEVELS.map(({ level }) => ({ id: mtbLevelCasingLayerId(level), ...base, filter: filters[mtbLevelCasingLayerId(level)], paint: mtbLevelPaint(level, strong).casing })),
    { id: MTB_TRAIL_LAYER_ID, ...base, filter: filters[MTB_TRAIL_LAYER_ID], paint: mtbTrailPaint(strong) },
    ...MTB_LEVELS.map(({ level }) => ({ id: mtbLevelLayerId(level), ...base, filter: filters[mtbLevelLayerId(level)], paint: mtbLevelPaint(level, strong).line })),
  ];
}

/**
 * Each overlay layer's filter in the ride time `when`, by layer id. Each routable layer
 * excludes the mountain-bike trails, which the not-for-routes layers (MTB_LAYER_IDS) draw,
 * unless `routableMtb` (MTB_TRAILS_ROUTABLE, above), when the routable layers draw them and
 * those draw nothing. In the Mass Ride map (`mass`) each also excludes the features
 * that carry a capacity (massStyle.js, massHides), but the mountain-bike layers, a map layer of their own (454).
 */
export function stressFilters(when = DEFAULT_WHEN, showHighLanes = highStressLanesOn(), mass = massRide, routable = routableMtb ?? MTB_TRAILS_ROUTABLE) {
  const filters = stressFiltersOf(when, showHighLanes, routable);
  if (!mass) return filters;
  // The mountain-bike trails' layers keep their own filters: their layer shows in every ride type (454), and nearly
  // every trail row carries a capacity (`rpm`, a path's default width), so `massHides` would draw none of them.
  return Object.fromEntries(Object.entries(filters).map(([id, filter]) => [id, isMtbLayerId(id) ? filter : ["all", filter, massHides]]));
}

function stressFiltersOf(when, showHighLanes, routableMtb) {
  const filters = {};
  // Every routable filter is ["all", drawnAt(when), <the mountain-bike cut, unless routableMtb>, ...its own clauses].
  // A level (the Mountain Bike ride type, slice 6): the trails up to it are routable, the harder ones are not.
  const upTo = typeof routableMtb === "number" ? routableMtb : null;
  const hidden = upTo !== null ? [["any", mtbHides, mtbWithin(upTo)]] : routableMtb ? [] : [mtbHides];
  // The not-for-routes lines: the mountain-bike trails, or nothing once they are routable (or, at a level,
  // only the trails above it). The shared ticks draw every one of them; the grey dashes and their white edge
  // the unrated ones (no `mtb_level`), and each level's white edge and line the trails of that level (456).
  const off = upTo !== null ? [["!", mtbWithin(upTo)]] : routableMtb ? [["boolean", false]] : [];
  filters[MTB_TICKS_LAYER_ID] = ["all", drawnAt(when), isMtbTrail, ...off];
  filters[MTB_TRAIL_LAYER_ID] = ["all", drawnAt(when), isMtbTrail, ["!", ["has", "mtb_level"]], ...off];
  filters[MTB_TRAIL_CASING_LAYER_ID] = filters[MTB_TRAIL_LAYER_ID];
  for (const { level } of MTB_LEVELS) {
    const filter = ["all", drawnAt(when), isMtbTrail, ["==", ["get", "mtb_level"], level], ...off];
    filters[mtbLevelCasingLayerId(level)] = filter;
    filters[mtbLevelLayerId(level)] = filter;
  }
  // The names (2026-10-10): every mountain-bike trail with one, rated or not.
  // At a level (slice 6) every trail keeps its name, routable or not.
  filters[MTB_LABEL_LAYER_ID] = ["all", drawnAt(when), isMtbTrail, ["has", "name"], ...(upTo !== null ? [] : off)];
  // The major trails' names (2026-10-21): every way that carries one (never a mountain-bike trail, which the
  // tiles name as `name`; the cut is the routable layers' all the same).
  filters[TRAIL_LABEL_LAYER_ID] = ["all", drawnAt(when), ...hidden, ["has", "trail_name"]];
  for (const tier of TIER_SHAPES) {
    const filter = ["all", drawnAt(when), ...hidden, ["==", tierAt(when), tier.tier]];
    // LTS 1's line and edge leave the surface-unknown trails to their own layers.
    const own = tier.tier === 1 ? [...filter, ["!", surfaceUnknown]] : filter;
    filters[`stress-${tier.tier}`] = own;
    filters[`stress-casing-${tier.tier}`] = own;
    if (tier.tier === 1) filters["stress-unknown"] = filters["stress-unknown-casing"] = [...filter, surfaceUnknown];
    if (tier.dash && hasGapLayer(tier.tier)) filters[`stress-gap-${tier.tier}`] = filter;
    if (hasRingLayer(tier.tier)) filters[`stress-ring-${tier.tier}`] = [...filter, ["!=", ["get", "unpaved"], true]];
    filters[`stress-unpaved-${tier.tier}`] = [...filter, ["==", ["get", "unpaved"], true]];
    if (tier.tier < 5) {
      // A half step's dash (441r-441v, 458): the feature's own tier is this one (not a road closed to cars
      // now, which draws as a path at 1, even one whose own tier is 1: the router drops its half then, review
      // CH-5) and it carries the half.
      const half = [...filter, ["==", ["get", "tier"], tier.tier], ["!", carFreeNow(when)], isHalfStep];
      filters[`stress-half-outline-${tier.tier}`] = half;
      filters[`stress-half-${tier.tier}`] = half;
    }
  }
  for (const facility of FACILITIES) {
    const filter = ["all", drawnAt(when), ...hidden, ["==", facilityAt(when), facility.facility]];
    // An unpaved trail is not given a path's rails (OWNER-DECISIONS 290: the
    // Lake Accotink singletrack read as "protected bike paths"): it draws as its
    // tier's line and the unpaved mark. A missing "unpaved" is an unknown
    // surface, which keeps its rails on a road that is not a trail, and not on
    // a trail.
    //
    // 376, A: a trail whose surface is not mapped has none either (surfaceUnknown): it may be
    // either, and drawn like a paved path it read as one.
    if (facility.facility === "path") filter.push(["!=", ["get", "unpaved"], true], ["!", surfaceUnknown]);
    // A painted lane is not drawn on LTS 4 and Avoid unless the rider asked
    // (a missing tier counts as 0, which draws it, as a rating-less road
    // has no stress to be high). The tile's own tier: a road closed to cars
    // is a path in this ride time, and is not in this layer at all.
    if (facility.facility === "lane" && !showHighLanes) filter.push(["<", ["to-number", ["get", "tier"], 0], HIGH_STRESS_LANE_MIN_TIER]);
    filters[`facility-${facility.facility}`] = filter;
  }
  return filters;
}

export function stressLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers.map((tier) => ({
    id: `stress-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-${tier.tier}`],
    paint: { ...linePaint(byUnpaved(tier.unpavedColor, tier.color, tier.gravelColor), tier.width, tier.tier >= BUSY_MIN_TIER, (zoom) => zoomedOutLine(tier, zoom)), ...(tier.dash ? { "line-dasharray": tier.dash } : {}) },
  }));
}

/**
 * The surface-unknown trails (OWNER-DECISIONS 376, A): LTS 1's line and edge, both dashed
 * (UNKNOWN_SURFACE_DASH) so the line does not read as a solid, paved path, with no rails and
 * no dark continuous edge: the edge is the dashes' own, so a gap shows the base map. The
 * edge's dash is the line's in its own width, which differs from the line's at z10-11, so it
 * follows the zoom (`unknownEdgeDash`). A tier other than 1 is drawn as it is (an
 * override on a trail), by its own layers.
 */
function unknownEdgeDash(tier, zoom) {
  const line = zoom === null ? tier.width : zoomedOutLine(tier, zoom);
  const casing = zoom === null ? casingWidth(tier) : zoomedOutCasing(tier, zoom);
  return UNKNOWN_SURFACE_DASH.map((d) => (d * line) / casing);
}

/** The edge's dash by zoom, for the map: one per zoomed-out grade, then the full widths' (a "step", as the widths are). */
export function unknownEdgeDashByZoom(tier) {
  return [
    "step",
    ["zoom"],
    ...zoomedOutStops((zoom) => ["literal", unknownEdgeDash(tier, zoom)]),
    ["literal", unknownEdgeDash(tier, null)],
  ];
}

export function unknownSurfaceLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  const tier = tiers[0];
  return [
    {
      id: "stress-unknown-casing",
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      filter: filters["stress-unknown-casing"],
      paint: { ...casingPaint(tier), "line-dasharray": unknownEdgeDashByZoom(tier) },
    },
    {
      id: "stress-unknown",
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      filter: filters["stress-unknown"],
      paint: { ...linePaint(tier.color, tier.width, false, (zoom) => zoomedOutLine(tier, zoom)), "line-dasharray": UNKNOWN_SURFACE_DASH },
    },
  ];
}

/**
 * The surface mark (OWNER-DECISIONS 279, 280): a road or trail the tiles say
 * is unpaved (their "unpaved", true or left out) is drawn with a dotted
 * centre line over its tier's line, in the tier's casing colour (which is
 * chosen to stand apart from the line), so a gravel trail does not read as a
 * smooth path. Shape, not colour: a dot pattern no tier or facility has. Not
 * drawn where the line is faint or hidden (z12-13 busy roads, alleys).
 * Its colour follows the line's: the brown's casing on a natural surface, the grey's on gravel (GRAVEL_PALETTES).
 */
export const UNPAVED_DASH = [1, 1.2];

/** The unpaved mark's width for a tier: a little under half the line, at least 1.5 px. */
export function unpavedWidth(tier) {
  return Math.max(1.5, tier.width * 0.4);
}

/**
 * The unpaved mark's width at z10 or z11: three fifths of the thinned line, so it
 * stays inside it, but never under ZOOMED_OUT_MIN_PX (the mark is the cue that
 * does not depend on colour: accessibility review SF1 of ZOOMED-TRAILS) and never
 * wider than it is from z12, so it does not shrink as the map zooms in.
 */
export function zoomedOutUnpavedWidth(tier, zoom) {
  return Math.min(unpavedWidth(tier), Math.max(ZOOMED_OUT_MIN_PX, zoomedOutLine(tier, zoom) * 0.6));
}

/** The mark's width by zoom: thinned below FULL_WIDTH_MIN_ZOOM, `unpavedWidth` from it. */
function unpavedWidthByZoom(tier) {
  return ["step", ["zoom"], ...zoomedOutStops((zoom) => zoomedOutUnpavedWidth(tier, zoom)), unpavedWidth(tier)];
}

export function unpavedLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers.map((tier) => ({
    id: `stress-unpaved-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-unpaved-${tier.tier}`],
    paint: {
      // The dots in the unpaved casing, which stands apart from the brown line (OWNER-DECISIONS 302); on gravel the grey's.
      "line-color": byUnpaved(tier.unpavedCasing, tier.gravelCasing, tier.gravelCasing),
      "line-width": unpavedWidthByZoom(tier),
      "line-opacity": byZoom(1, 0, tier.tier >= BUSY_MIN_TIER),
      "line-dasharray": UNPAVED_DASH,
    },
  }));
}

/**
 * A tier's casing paint: the band under the line at full strength; where the
 * line is faint, a thin dark ring around it (FAINT) as the second cue.
 */
function casingPaint(tier) {
  const busy = tier.tier >= BUSY_MIN_TIER;
  const edge = faintEdgeColour(tier);
  const full = byUnpaved(tier.unpavedCasing, tier.casing, tier.gravelCasing);
  return {
    "line-color": byZoom(full, edge, busy, full),
    "line-width": byZoom(casingWidth(tier), FAINT.edgePx, busy, 0, (zoom) => zoomedOutCasing(tier, zoom)),
    "line-gap-width": byZoom(0, tier.width * FAINT.widthScale, busy),
    "line-opacity": byZoom(1, FAINT.edgeOpacity, busy),
  };
}

/** The casing under each tier's line, drawn first so the tier sits on it. */
export function stressCasingLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers.map((tier) => ({
    id: `stress-casing-${tier.tier}`,
    type: "line",
    source: sourceId,
    "source-layer": STRESS_TILE_LAYER,
    filter: filters[`stress-casing-${tier.tier}`],
    paint: casingPaint(tier),
  }));
}

/**
 * The two-tone default's outer ring (OWNER-DECISIONS 371, on the final preview: the
 * "thin near-black outer ring" proposed for 351's 3:1 break). Two-tone LTS 3 (yellow on
 * orange) and LTS 4 (orange on red) are not 3:1 from the light base map, line or edge;
 * a near-black ring a pixel wide outside the edge is (13:1 and more from every surface,
 * and 3:1 or more from the orange and red edges it rings), and keeps both of the owner's
 * colours. Drawn on the map (`ringLayers`, under everything else of the overlay, so a
 * facility rail still shows over it), round the route's sections (`route-ring`) and in
 * the legend's swatches. Paved roads only: an unpaved one is the brown or the gravel grey ramp, each 3:1
 * on its own casing. Not drawn where the line is faint (z12-13), which keeps its own edge.
 * A tier with no `ring` has its ring layer drawn transparent, so a palette flip needs no
 * new layer.
 *
 * `legendRing`: the same idea for the legend alone, where Avoid's red on its near-black
 * edge is 2.76:1 on the dark theme's soft panel (351's last 3:1 break): a mid-grey ring
 * round the Avoid swatch (5.7:1 from that panel, 7.4:1 from the edge). The map is light,
 * and Avoid's edge is already 3:1 there, so the map has no such ring.
 */
export const RING_COLOUR = "#1c1917";
export const LEGEND_RING_COLOUR = "#9aa0a6";

/** A ring's width: a pixel each side of the casing. */
export function ringWidth(tier) {
  return casingWidth(tier) + 2;
}

/** Whether a tier has a ring in some palette: only those get a ring layer. */
export function hasRingLayer(tier) {
  return Object.values(PALETTES).some((p) => p[tier].ring);
}

export function ringLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  return tiers
    .filter((tier) => hasRingLayer(tier.tier))
    .map((tier) => ({
      id: `stress-ring-${tier.tier}`,
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      filter: filters[`stress-ring-${tier.tier}`],
      paint: {
        "line-color": tier.ring ?? "rgba(0, 0, 0, 0)",
        "line-width": ringWidth(tier),
        "line-opacity": byZoom(1, 0, tier.tier >= BUSY_MIN_TIER),
      },
    }));
}

/**
 * HALF STEPS (OWNER-DECISIONS 441i-441v, 458, 458a, 458b, 460.1). The tiles carry a half step as its
 * lower `tier` plus `half: true` (core/stress_tiles.py), so below HALF_STEP_MIN_ZOOM a half step draws
 * exactly as its lower level (460.1: "The level below makes more sense"; 1.5 looks like LTS 1). From
 * HALF_STEP_MIN_ZOOM it keeps the lower level's whole look - base colour, casing, width and its own
 * pattern (441v) - and over it goes a dash in the NEXT level's base colour (441u: "Basically the dash
 * would be the next one up's base color"), Option A of the mock-up (458), sparse blocks:
 *
 * - 1.5, 2.5, 3.5: HALF_STEP_DASH [1.5, 4.5] at the lower level's full line width, in the base colour of
 *   LTS 2, 3 or 4 (1.5's is LTS 2's green #57a06c on the default palette and blue on the colour-blind
 *   one, 458a);
 * - 4.5: Avoid's dash-dot [5, 1, 0.5, 1] at LTS 4's width in Avoid's base colour (441s). It is never
 *   drawn as Avoid (441k).
 *
 * Two dashes are too close to their line (458b, "yes add them"): the default palette's 3.5 (LTS 4's
 * orange on LTS 3's yellow, about 1.5:1) and the colour-blind palette's 4.5 (Avoid's blue-black on LTS
 * 4's dark red, about 1.6:1). Each gets a thin outline on the dash only (HALF_OUTLINES):
 * a pixel each side, drawn under the dash with the same pattern scaled to its own width, in a colour at
 * least 3:1 from both the dash and the line (HALF_OUTLINE_MIN_CONTRAST; halfSteps.test.ts and the
 * browser a11y suite hold it). Every other half step's outline layer is drawn transparent, so a palette
 * flip needs no new layer. Colour is not the only cue: the dash's shape is one no whole level uses, and
 * the road panel says the exact step in words (441k).
 *
 * Not drawn where the line itself is faint or hidden (a busy road beside a separate bikeway, an alley):
 * the dash follows the line's own `byZoom` opacity, at nothing where the line is faint.
 */
export const HALF_STEP_MIN_ZOOM = 15;
export const HALF_STEP_DASH = [1.5, 4.5];
/** 4.5's dash: Avoid's own dash-dot (441s), never Avoid's look (441k). */
export const HALF_STEP_TOP_DASH = [5, 1, 0.5, 1];
export const HALF_OUTLINE_PX = 1;
export const HALF_OUTLINE_MIN_CONTRAST = 3;
const isHalfStep = ["==", ["get", "half"], true];

/** The half step above `tier` (1-4): its dash colour, pattern and width, and its outline (or null). */
export function halfStep(tier, tiers = currentTiers()) {
  const lower = tiers.find((t) => t.tier === tier);
  const upper = tiers.find((t) => t.tier === tier + 1);
  if (!lower || !upper || tier >= 5) return null;
  const dash = tier === 4 ? HALF_STEP_TOP_DASH : HALF_STEP_DASH;
  return {
    tier,
    step: tier + 0.5,
    color: upper.color,
    line: lower.color,
    width: lower.width,
    dash,
    outline: lower.halfOutline ?? null,
  };
}

/** A dash pattern in a wider line's units, so its blocks fall where the narrower line's do. */
export function scaledDash(dash, width, wider) {
  return dash.map((part) => Math.round(((part * width) / wider) * 1000) / 1000);
}

export function halfStepLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  const filters = stressFilters(when);
  const layers = [];
  for (const tier of tiers.filter((t) => t.tier < 5)) {
    const half = halfStep(tier.tier, tiers);
    const busy = tier.tier >= BUSY_MIN_TIER;
    const outlineWidth = half.width + 2 * HALF_OUTLINE_PX;
    layers.push({
      id: `stress-half-outline-${tier.tier}`,
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      minzoom: HALF_STEP_MIN_ZOOM,
      filter: filters[`stress-half-outline-${tier.tier}`],
      paint: {
        "line-color": half.outline ?? "rgba(0, 0, 0, 0)",
        "line-width": outlineWidth,
        "line-opacity": byZoom(1, 0, busy),
        "line-dasharray": scaledDash(half.dash, half.width, outlineWidth),
      },
    });
    layers.push({
      id: `stress-half-${tier.tier}`,
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      minzoom: HALF_STEP_MIN_ZOOM,
      filter: filters[`stress-half-${tier.tier}`],
      paint: {
        "line-color": half.color,
        "line-width": half.width,
        "line-opacity": byZoom(1, 0, busy),
        "line-dasharray": half.dash,
      },
    });
  }
  return layers;
}

/** How much wider a casing is than its tier's line: a pixel on each side. */
export const CASING_EXTRA_PX = 2;

/** A tier's casing width: its line and the casing's extra (wider with the accessibility switch on). */
export function casingWidth(tier) {
  return tier.width + (tier.casingExtra ?? CASING_EXTRA_PX);
}

/**
 * Bike facilities (owner request of 2026-09-27: off-road paths, then protected
 * lanes, well above painted lanes, above ordinary streets; sharrows count as
 * nothing). The tiles carry a "facility" of path, protected, lane or none once
 * the segment table has it (core/stress_tiles.py), and nothing before.
 *
 * Each is drawn as a pair of rails either side of the stress line - a wider
 * line under the tier's casing - so the tier's own colour and dash stay
 * readable on the same street and the route's blue is not reused. A path's
 * rails are left off an unpaved trail (stressFilters; OWNER-DECISIONS 290),
 * and are 2.5 px, not the protected lane's 4: a trail network drawn with two
 * 4 px dark rails a line read as "double-outlined", heavier than the streets
 * around it, and the solid line, not its weight, is what says "path". The owner,
 * on three violets that were hard to tell apart (OWNER-DECISIONS 276), and
 * that "paint isn't protection and lots of maps overemphasize it" (277): shape
 * comes first and colour second. A path's rails are solid; a
 * protected lane's are bold and broken into short blocks like a row of posts;
 * a painted lane's are the thinnest line on the map, a sparse dotted rail in
 * the palest colour that is still 3:1 from the base map, and drawn under the
 * other two. The colours are spread in hue and lightness as well (dark
 * indigo, magenta, light violet), clear of every stress colour and the
 * route's blue (stressContrast.test.ts holds the separation). "none"
 * (sharrows included) draws nothing. FACILITIES is in the legend's order
 * (the real infrastructure first, painted last); FACILITY_DRAW_ORDER is the
 * map's, bottom first.
 */
export const FACILITIES = [
  { facility: "path", short: "Path", label: "Off-road bike path", color: "#4c1d95", rail: 2.5, dash: null },
  { facility: "protected", short: "Protected", label: "Protected bike lane", color: "#a21caf", rail: 4, dash: [0.3, 0.3] },
    // `strongRail`: the painted rail with the accessibility switch on (a pixel
  // of 0.9 px dots fades to far under its colour's 3.26:1 once antialiased;
  // SF6 of the salience review). Still the thinnest rail; the default is the
  // weakest of all.
  { facility: "lane", short: "Painted", label: "Painted lane (no separation)", color: "#9370f0", rail: 1, strongRail: 1.5, dash: [0.14, 0.4] },
];

/** The rails' drawing order, bottom first: painted under protected under path. */
export const FACILITY_DRAW_ORDER = ["lane", "protected", "path"];

/**
 * Painted lanes (the tiles' facility "lane") on roads of this stress tier or
 * above - LTS 4 and Avoid - are not drawn, on the map or counted in the route
 * panel, unless the rider turns "Show bike lanes on high-stress roads" on
 * (OWNER-DECISIONS 275, the owner's words: "Kenilworth avenue is hillarious at
 * having a bike lane on it.").
 * Protected lanes and paths are drawn at every tier, and the stress ratings
 * and the data are untouched.
 */
export const HIGH_STRESS_LANE_MIN_TIER = 4;

/** Where the switch is remembered, per browser: "on" or "off". */
export const HIGH_STRESS_LANES_STORAGE_KEY = "routemaker.highStressLanes";

/** What this browser remembers of the lane switch: true, false, or null (nothing, a value this page did not write, or storage throws). */
export function storedHighStressLanes(storage = browserStorage()) {
  try {
    const value = storage?.getItem(HIGH_STRESS_LANES_STORAGE_KEY);
    return value === "on" ? true : value === "off" ? false : null;
  } catch {
    return null;
  }
}

/** Remember the lane switch for this browser; false when storage refused. */
export function rememberHighStressLanes(on, storage = browserStorage()) {
  try {
    if (!storage) return false;
    storage.setItem(HIGH_STRESS_LANES_STORAGE_KEY, on ? "on" : "off");
    return true;
  } catch {
    return false;
  }
}

/** Off unless the rider turned it on: the default hides painted lanes on LTS 4 and Avoid. */
let highStressLanes = storedHighStressLanes() === true;
/** @type {Set<(on: boolean) => void>} */
const laneListeners = new Set();

/** Whether painted lanes on LTS 4 and Avoid roads are shown. */
export function highStressLanesOn() {
  return highStressLanes;
}

/** Turn the lane switch on or off now and tell the subscribers; kept for this browser unless `remember` is false. */
export function setHighStressLanes(on, { remember = true, storage } = {}) {
  const next = on === true;
  if (remember) rememberHighStressLanes(next, storage);
  if (next === highStressLanes) return;
  highStressLanes = next;
  for (const listener of [...laneListeners]) listener(next);
}

/** Call `listener(on)` whenever the lane switch changes; returns the way to stop. */
export function subscribeHighStressLanes(listener) {
  laneListeners.add(listener);
  return () => {
    laneListeners.delete(listener);
  };
}

/**
 * The "Mountain-bike trails" map layer (OWNER-DECISIONS 454): one of the optional layers every
 * ride type has, signed in or out, off until the rider turns it on. It shows or hides the
 * not-for-routes line (`mtb-trail`, 452a) and nothing else: the routable layers never draw these
 * trails either way, and routing is unchanged. Kept per browser like the lane switch: "on" or "off".
 */
export const MTB_TRAILS_STORAGE_KEY = "routemaker.mtbTrails";

/** What this browser remembers of the layer: true, false, or null (nothing, a value this page did not write, or storage throws). */
export function storedMtbTrails(storage = browserStorage()) {
  try {
    const value = storage?.getItem(MTB_TRAILS_STORAGE_KEY);
    return value === "on" ? true : value === "off" ? false : null;
  } catch {
    return null;
  }
}

/** Remember the layer for this browser; false when storage refused. */
export function rememberMtbTrails(on, storage = browserStorage()) {
  try {
    if (!storage) return false;
    storage.setItem(MTB_TRAILS_STORAGE_KEY, on ? "on" : "off");
    return true;
  } catch {
    return false;
  }
}

/** Off until the rider turns it on (454). */
let mtbTrails = storedMtbTrails() === true;
/** @type {Set<(on: boolean) => void>} */
const mtbListeners = new Set();

/** Whether the mountain-bike trail layer is on. */
export function mtbTrailsOn() {
  return mtbTrails;
}

/** Turn the layer on or off now and tell the subscribers; kept for this browser unless `remember` is false. */
export function setMtbTrails(on, { remember = true, storage } = {}) {
  const next = on === true;
  if (remember) rememberMtbTrails(next, storage);
  if (next === mtbTrails) return;
  mtbTrails = next;
  for (const listener of [...mtbListeners]) listener(next);
}

/** Call `listener(on)` whenever the layer is turned on or off; returns the way to stop. */
export function subscribeMtbTrails(listener) {
  mtbListeners.add(listener);
  return () => {
    mtbListeners.delete(listener);
  };
}

/** How far a facility's rail shows beyond each side of the casing: its `strongRail` with the accessibility switch on, where it has one. */
export function railWidth(facility, strong = false) {
  return strong && facility.strongRail ? facility.strongRail : facility.rail;
}

/** A facility's rails: wide enough to show its rail (railWidth) beyond each side of the casing. */
export function facilityWidth(facility, tierWidth, casingExtra = CASING_EXTRA_PX, strong = false) {
  return tierWidth + casingExtra + 2 * railWidth(facility, strong);
}

/**
 * A facility's rail width, by the tier its feature draws at in `when`, in the
 * tiers' widths and casings in use (the accessibility switch makes both
 * stronger, and the rails sit outside the casing). A tier the style has no
 * entry for (one added later) is drawn at LTS 1's width.
 */
export function facilityWidthAt(facility, when = DEFAULT_WHEN, tiers = currentTiers()) {
  const byTier = tiers.flatMap((tier) => [tier.tier, facilityWidth(facility, tier.width, tier.casingExtra, tier.strong)]);
  const full = ["match", tierAt(when), ...byTier, facilityWidth(facility, tiers[0].width, tiers[0].casingExtra, tiers[0].strong)];
  const thinned = (zoom) => {
    const byTierOut = tiers.flatMap((tier) => [tier.tier, zoomedOutFacilityWidth(facility, tier, zoom)]);
    return ["match", tierAt(when), ...byTierOut, zoomedOutFacilityWidth(facility, tiers[0], zoom)];
  };
  return ["step", ["zoom"], ...zoomedOutStops(thinned), full];
}

/**
 * A facility's rails at z10 or z11: the casing, and the rail's own thinned width
 * each side (ZOOMED_OUT_SCALE), never under ZOOMED_OUT_MIN_PX (a painted rail would
 * otherwise be 0.4 px at z10).
 */
export function zoomedOutFacilityWidth(facility, tier, zoom) {
  const rail = Math.max(ZOOMED_OUT_MIN_PX, railWidth(facility, tier.strong) * ZOOMED_OUT_SCALE[zoom].rail);
  return zoomedOutCasing(tier, zoom) + 2 * rail;
}

/**
 * The length of a legend swatch's line, in pixels: long enough to show at least
 * one whole dash cycle of every tier and rail, plain and strong (the a11y review's
 * SF5: at 40 px the strong LTS 4 [8, 1] x 5.5 px = 49.5 px and Avoid's
 * [5, 1, 0.5, 1] x 7 px = 52.5 px each drew as a plain solid line, so the
 * dash-dot that tells Avoid apart never showed). stressSalience.test.ts holds
 * every dash period times its line's width to it.
 */
export const LEGEND_SWATCH_PX = 64;

/**
 * The panel legend's stroke widths, as the map draws the same lines: each
 * tier's line and casing, and for the bike-facility legend (drawn on LTS 1's
 * line) the casing and each facility's rails. With the accessibility switch
 * on, the casings and rails are wider; the legend reads them here so it
 * cannot fall out of step with the map.
 */
export function legendWidths(tiers = currentTiers()) {
  const base = tiers[0];
  return {
    tiers: tiers.map((tier) => ({ tier: tier.tier, line: tier.width, casing: casingWidth(tier), ring: ringWidth(tier) })),
    facilityCasing: casingWidth(base),
    rails: Object.fromEntries(FACILITIES.map((facility) => [facility.facility, facilityWidth(facility, base.width, base.casingExtra, base.strong)])),
  };
}

export function facilityLayers(sourceId = "stress", when = DEFAULT_WHEN, showHighLanes = highStressLanesOn()) {
  const filters = stressFilters(when, showHighLanes);
  const ordered = FACILITY_DRAW_ORDER.map((name) => FACILITIES.find((f) => f.facility === name));
  return ordered.map((facility) => {
    const paint = {
      "line-color": facility.color,
      "line-width": facilityWidthAt(facility, when),
    };
    if (facility.dash) paint["line-dasharray"] = facility.dash;
    return {
      id: `facility-${facility.facility}`,
      type: "line",
      source: sourceId,
      "source-layer": STRESS_TILE_LAYER,
      filter: filters[`facility-${facility.facility}`],
      paint,
    };
  });
}

/**
 * The overlay's layers in the order they are added to the map, bottom first:
 * the facility rails, every casing, then every tier. A casing drawn after a
 * tier would paint over it, solid, wherever the two meet - including its own
 * tier, which would then vanish under its casing; rails drawn over a casing
 * would do the same to the whole line.
 */
export function stressOverlayLayers(sourceId = "stress", when = DEFAULT_WHEN, tiers = currentTiers()) {
  return [
    // The mountain-bike trails' layer (452a, 454, 456), under every routable layer.
    ...mtbTrailLayers(sourceId, when),
    ...ringLayers(sourceId, when, tiers),
    ...facilityLayers(sourceId, when),
    ...stressCasingLayers(sourceId, when, tiers),
    ...gapLayers(sourceId, when, tiers),
    ...unknownSurfaceLayers(sourceId, when, tiers),
    ...stressLayers(sourceId, when, tiers),
    ...unpavedLayers(sourceId, when, tiers),
    // Half steps' dashes from street level (441r-441v, 458), over their lower level's line.
    ...halfStepLayers(sourceId, when, tiers),
    // The major trails' names (2026-10-21), over every line.
    ...trailLabelLayers(sourceId, when),
    // The mountain-bike trails' names (2026-10-10), over every routable line, so a route does not hide them.
    ...mtbLabelLayers(sourceId, when),
    // The Mass Ride map's own layers, over these, from its own tiles (core/mass_tiles.py): drawn
    // only in that mode, where every layer above is hidden (lib/mapGlue.ts; OWNER-DECISIONS 417a).
    ...massLayers(MASS_SOURCE_ID, STRESS_TILE_LAYER, accessibilityOn()),
  ];
}

/** Legend entries, which carry the label the colour alone cannot. */
export function legend(tiers = currentTiers()) {
  return tiers.map(({ tier, short, label, color, dash, width, casing, gap, ring, legendRing }) => ({
    tier,
    short,
    label,
    color,
    dash,
    width,
    casing,
    gap,
    ring,
    legendRing,
  }));
}
