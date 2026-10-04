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
const TIER_SHAPES = [
  // A solid line is `null`, never [1]: a one-entry dash array is an odd list,
  // which SVG (the legend) repeats into [1, 1] - a dashed swatch for a line
  // the map draws solid (OWNER-DECISIONS 279). Every dash here has an even length.
  { tier: 1, label: "Comfortable for most people", short: "LTS 1", dash: null, width: 2.5 },
  { tier: 2, label: "Comfortable for most adults", short: "LTS 2", dash: [4, 1], width: 3.25 },
  { tier: 3, label: "For confident riders", short: "LTS 3", dash: [2, 0.4], width: 4.25 },
  { tier: 4, label: "Heavy or fast traffic", short: "LTS 4", dash: [8, 1], width: 5 },
  // Not a Furth tier: legal for a bicycle and best avoided (the owner's fifth
  // category, 2026-09-27): the widest line and a dash-dot nothing else uses.
  { tier: 5, label: "Legal, but best avoided", short: "Avoid", dash: [5, 1, 0.5, 1], width: 6.5 },
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
 * lists them (LTS 3 and LTS 4 are not 3:1 on the base map, the greyscale order
 * is lost, LTS 3 and 4 are close for a deuteranope, and LTS 4 is less
 * saturated than LTS 3), and defaultPalette.test.ts holds the default to every
 * other rule and to exactly those.
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
 *   red on black. Closer to the owner's words; LTS 3 is not 3:1 on the base map (its casing 2.2:1, the line
 *   on its casing 1.5:1) and the greyscale order is lost (stressContrast.test.ts
 *   holds the chosen palette to the rule, and reports the other).
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

/** The palette the map uses unless the address or the accessibility switch asks for another. */
export const DEFAULT_PALETTE = "twotone";

/**
 * The palettes' names in a link (`?palette=`), which say nothing of who uses them
 * (OWNER-DECISIONS 321: "Make sure that the link text doesn't scream 'disability' in the
 * parameters."): "warm" the default, "twotone" the owner's second reading, "cool" the
 * blue-and-orange one the switch turns on. The names in the code stay as they were.
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
  return Object.values(PALETTES).some((p) => p[tier].gap) || Object.values(UNPAVED_PALETTES).some((p) => p[tier].gap);
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
          "line-color": byUnpaved(tier.unpavedGap, tier.gap),
          "line-width": byZoom(tier.width, tier.width * FAINT.widthScale, busy),
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
 *   LTS 3 is a yellow (#f2c21b) a warm tan would sit on (6 CIEDE2000 under
 *   deuteranopia). Its LTS 1 is a pale taupe (#e6dad4; 350, 371): #d4bba6 was 9.1
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
    2: { color: "#ac8b73", casing: "#1a2638", gap: "#7a8fa3" },
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

/** A colour that is `unpaved` on a feature the tiles say is unpaved, else `paved`. */
const byUnpaved = (unpaved, paved) => ["case", ["==", ["get", "unpaved"], true], unpaved, paved];

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
 * time the map follows: "weekend", "weekday_rush" or "weekday_offpeak".
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
function byZoom(full, faint, busy, hidden = 0) {
  const at = (zoom) => {
    const alley = zoom >= ALLEY_MIN_ZOOM ? faint : hidden;
    const road = !busy
      ? full
      : ["case", besideBikeway, zoom >= BESIDE_ROAD_MIN_ZOOM ? faint : hidden, zoom >= SOLID_MIN_ZOOM ? full : faint];
    return ["case", isAlley, alley, road];
  };
  return [
    "step",
    ["zoom"],
    at(SOLID_MIN_ZOOM - 1),
    SOLID_MIN_ZOOM,
    at(SOLID_MIN_ZOOM),
    BESIDE_ROAD_MIN_ZOOM,
    at(BESIDE_ROAD_MIN_ZOOM),
    ALLEY_MIN_ZOOM,
    at(ALLEY_MIN_ZOOM),
  ];
}

/** A line's paint, faint and late as byZoom says. */
function linePaint(color, width, busy) {
  return {
    "line-color": color,
    "line-width": byZoom(width, width * FAINT.widthScale, busy),
    "line-opacity": byZoom(1, FAINT.opacity, busy),
  };
}

/** Each overlay layer's filter in the ride time `when`, by layer id. */
export function stressFilters(when = DEFAULT_WHEN, showHighLanes = highStressLanesOn()) {
  const filters = {};
  for (const tier of TIER_SHAPES) {
    const filter = ["all", drawnAt(when), ["==", tierAt(when), tier.tier]];
    filters[`stress-${tier.tier}`] = filter;
    filters[`stress-casing-${tier.tier}`] = filter;
    if (tier.dash && hasGapLayer(tier.tier)) filters[`stress-gap-${tier.tier}`] = filter;
    if (hasRingLayer(tier.tier)) filters[`stress-ring-${tier.tier}`] = [...filter, ["!=", ["get", "unpaved"], true]];
    filters[`stress-unpaved-${tier.tier}`] = [...filter, ["==", ["get", "unpaved"], true]];
  }
  for (const facility of FACILITIES) {
    const filter = ["all", drawnAt(when), ["==", facilityAt(when), facility.facility]];
    // An unpaved trail is not given a path's rails (OWNER-DECISIONS 290: the
    // Lake Accotink singletrack read as "protected bike paths"): it draws as its
    // tier's line and the unpaved mark. A missing "unpaved" is an unknown
    // surface, which keeps its rails.
    if (facility.facility === "path") filter.push(["!=", ["get", "unpaved"], true]);
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
    paint: { ...linePaint(byUnpaved(tier.unpavedColor, tier.color), tier.width, tier.tier >= BUSY_MIN_TIER), ...(tier.dash ? { "line-dasharray": tier.dash } : {}) },
  }));
}

/**
 * The surface mark (OWNER-DECISIONS 279, 280): a road or trail the tiles say
 * is unpaved (their "unpaved", true or left out) is drawn with a dotted
 * centre line over its tier's line, in the tier's casing colour (which is
 * chosen to stand apart from the line), so a gravel trail does not read as a
 * smooth path. Shape, not colour: a dot pattern no tier or facility has. Not
 * drawn where the line is faint or hidden (z12-13 busy roads, alleys).
 * `is_rough` is not in the tiles; only "unpaved" is.
 */
export const UNPAVED_DASH = [1, 1.2];

/** The unpaved mark's width for a tier: a little under half the line, at least 1.5 px. */
export function unpavedWidth(tier) {
  return Math.max(1.5, tier.width * 0.4);
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
      // The dots in the unpaved casing, which stands apart from the brown line (OWNER-DECISIONS 302).
      "line-color": tier.unpavedCasing,
      "line-width": unpavedWidth(tier),
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
  const full = byUnpaved(tier.unpavedCasing, tier.casing);
  return {
    "line-color": byZoom(full, edge, busy, full),
    "line-width": byZoom(casingWidth(tier), FAINT.edgePx, busy),
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
 * the legend's swatches. Paved roads only: an unpaved one is the brown ramp, which is 3:1
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
  return ["match", tierAt(when), ...byTier, facilityWidth(facility, tiers[0].width, tiers[0].casingExtra, tiers[0].strong)];
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
    ...ringLayers(sourceId, when, tiers),
    ...facilityLayers(sourceId, when),
    ...stressCasingLayers(sourceId, when, tiers),
    ...gapLayers(sourceId, when, tiers),
    ...stressLayers(sourceId, when, tiers),
    ...unpavedLayers(sourceId, when, tiers),
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
