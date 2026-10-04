/**
 * OWNER-DECISIONS 351: "2 tone is better", "Make two-tone the default". The two-tone palette
 * is the default in the owner's colours, and where those colours break a rule the warm
 * palette was tuned to, the break is reported, not fixed silently (351: "If two-tone's
 * colours break any of them, report it rather than silently changing the owner's choice").
 * 371 (the owner, on the final preview) took two of the proposed fixes: the near-black outer
 * ring round LTS 3 and LTS 4 (which makes both 3:1 on the base map), and the yellow #f3c81a
 * (which puts LTS 3 and LTS 4 1.4:1 apart for a deuteranope); and the legend's grey ring
 * round Avoid mends Avoid on the dark soft panel. What is left is below. The tests hold the
 * default to every other rule and to exactly these breaks: one more is a failure, and one
 * fewer (a rule the default now keeps) is a failure too, so this list cannot go stale.
 * defaultPalette.test.ts measures each; docs/DEVELOPMENT.md, "The default palette (351)",
 * has the figures.
 */
export const DEFAULT_CONFLICTS = {
  /**
   * The line on its own edge: LTS 3's yellow on its orange edge (1.53:1) and LTS 4's orange on
   * its red edge (2.34:1), inside the ring, on the map and on the route. The ring makes the
   * whole line 3:1 on the map; the two colours inside it are the two-tone reading itself.
   */
  lineOnEdgeBelowThreeToOne: ["LTS 3", "LTS 4"],
  /**
   * Greyscale print: luminance no longer falls with stress. LTS 3's yellow (0.60) is the
   * lightest tier, lighter than LTS 1 (0.57), and LTS 4's orange (0.38) is lighter than LTS 2
   * (0.28). Every neighbouring pair is still 1.4:1 or more apart. A ring does not change it.
   */
  greyscaleOutOfOrder: ["LTS 3", "LTS 4"],
  /** For a deuteranope, neighbouring tiers under 1.4:1 in luminance: none since 371's yellow. */
  deuteranopeTooClose: [] as string[][],
  /** 274's salience: LTS 4's orange (CIELAB chroma 72.5) is less saturated than LTS 3's yellow. A ring does not change it. */
  lts4NotMoreSaturated: true,
  /** Avoid against LTS 4: 17.8 CIEDE2000 under deuteranopia, under the warm palette's 20 (the dash-dot, width and edge still differ). A ring does not change the lines. */
  avoidNearLts4: true,
  /** Avoid on the panels: none since 371's legend ring. */
  avoidOnDarkPanel: [] as string[],
} as const;
