/**
 * OWNER-DECISIONS 351: "2 tone is better", "Make two-tone the default". The two-tone palette
 * is the default in the owner's own colours, and where those colours break a rule the warm
 * palette was tuned to, the break is reported to the owner, not fixed silently (351: "If
 * two-tone's colours break any of them, report it rather than silently changing the owner's
 * choice"). The tests hold the default to every other rule and to exactly these breaks: one
 * more is a failure, and one fewer (a rule the default now keeps) is a failure too, so this
 * list cannot go stale. defaultPalette.test.ts measures each; docs/DEVELOPMENT.md, "The
 * default palette (351)", has the figures and the smallest tweak proposed for each.
 */
export const DEFAULT_CONFLICTS = {
  /**
   * WCAG 1.4.11's 3:1 for a graphic: LTS 3's yellow on its orange edge (1.46:1) and LTS 4's
   * orange on its red edge (2.34:1) - neither line nor edge is 3:1 from the light base map, the
   * light panel or the line's own route halo.
   */
  belowThreeToOne: ["LTS 3", "LTS 4"],
  /**
   * Greyscale print: luminance no longer falls with stress. LTS 3's yellow (0.58) is the
   * lightest tier, lighter than LTS 1 (0.57), and LTS 4's orange (0.38) is lighter than LTS 2
   * (0.28). Every neighbouring pair is still 1.4:1 or more apart, so they are told apart, but
   * not ordered.
   */
  greyscaleOutOfOrder: ["LTS 3", "LTS 4"],
  /** For a deuteranope LTS 3 and LTS 4 are 1.38:1 apart in luminance, under the 1.4:1 floor. */
  deuteranopeTooClose: [["LTS 3", "LTS 4"]],
  /** 274's salience: LTS 4's orange (CIELAB chroma 72.5) is less saturated than LTS 3's yellow (78.7). */
  lts4NotMoreSaturated: true,
  /** Avoid against LTS 4: 17.8 CIEDE2000 under deuteranopia, under the warm palette's 20 (the dash-dot, width and edge still differ). */
  avoidNearLts4: true,
  /** Avoid's red on its near-black edge is 2.76:1 from the dark theme's soft panel (#262a32). */
  avoidOnDarkPanel: ["#262a32"],
} as const;
