/**
 * Avoid as the route draws it (OWNER-DECISIONS 397: "Avoid as a single color should be magenta. It's
 * a very striking danger color. Only do if a route uses it"): one magenta for the route line
 * (routeColours.ts), the route panel's stress bar (stressBar.ts) and the route chart (profileChart.ts
 * AVOID_FILL; a test holds them equal). A module of its own so the bar and the line can share it
 * without importing each other.
 */
export const ROUTE_AVOID_MAGENTA = "#d6008f";
/** The near-black under it (the route's halo, the bar's cross-hatch): 4.1:1 from the magenta. */
export const ROUTE_AVOID_HALO = "#14040a";
/**
 * The cue on the route line that is not colour: a white dash-dot down the middle of a paved Avoid
 * section, 4.9:1 from the magenta. In the high contrast palette the magenta is only 6 CIEDE2000 from
 * LTS 3 under tritanopia, at the same lightness and on the same dark halo, so without it a stretch
 * of Avoid beside LTS 3 was told by colour alone (ELEVATION-CHART r3 accessibility, S1). The overlay's
 * own Avoid is a dash-dot too (stressStyle.js). Lengths are in mark widths, as MapLibre's dasharray
 * is: a long dash, a gap, a dot, a gap, far from the unpaved mark's even dots (UNPAVED_DASH).
 */
export const ROUTE_AVOID_MARK = "#ffffff";
export const ROUTE_AVOID_MARK_DASH: readonly number[] = [3, 1.5, 1, 1.5];
