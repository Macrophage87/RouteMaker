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
   * The line on its own edge: LTS 3's yellow on its orange edge (1.53:1) and LTS 3.5's orange on
   * its red edge (2.34:1, LTS 4's look until 2026-10-31), inside the ring, on the map and on the
   * route. The ring makes the whole line 3:1 on the map; the two colours inside it are the
   * two-tone reading itself. LTS 4's red is 3:1 on its near-black red edge since 2026-10-31.
   */
  lineOnEdgeBelowThreeToOne: ["LTS 3", "LTS 3.5"],
  /**
   * The same figure read as the dash pattern (the re-check's N-E): LTS 3's gaps show its orange
   * edge, 1.53:1 from the yellow, so its dash, the cue that is not colour, is faint for low
   * vision in the default. An owner trade (292, 351, 371); the cool palette has no such gap.
   */
  lts3DashGapFaint: true,
  /**
   * LTS 3 against LTS 4 for a deuteranope: 9.2 CIEDE2000 with LTS 4's orange (the re-check's N-B);
   * 23.2 since LTS 4 became a red (2026-10-31), so no longer reported.
   */
  lts3Lts4DeutanUnderTen: false,
  /**
   * Paved against unpaved of the same tier, under 10 CIEDE2000 under some vision (the re-check's
   * SF-A), in every palette: the dotted centre mark tells them apart there. Two-tone's LTS 2 was
   * 2.1 for a deuteranope and is 10.5 since its unpaved brown moved to #c2a698; what is left:
   */
  unpavedSameTierClose: { twotone: ["LTS 1"], blended: ["LTS 1", "LTS 2", "LTS 4", "Avoid"], cvd: ["LTS 4"] } as Record<string, string[]>,
  /**
   * Greyscale print: luminance no longer falls with stress. LTS 3's yellow (0.60) is the
   * lightest tier, lighter than LTS 1 (0.57). (LTS 4's red, 0.18, is darker than LTS 2 since
   * 2026-10-31.) Every neighbouring pair is still 1.4:1 or more apart. A ring does not change it.
   */
  greyscaleOutOfOrder: ["LTS 3"],
  /**
   * For a deuteranope, neighbouring tiers under 1.4:1 in luminance: LTS 4's red against Avoid's
   * magenta (1.09:1, 2026-10-31). Their edges (near-black red against white and a near-black ring),
   * Avoid's dash-dot and its width still tell them apart.
   */
  deuteranopeTooClose: [["LTS 4", "Avoid"]] as string[][],
  /** 274's salience: LTS 4 is not 10 CIELAB chroma more saturated than LTS 3's yellow (80): its orange was 72.5, its red (2026-10-31) is 87. A ring does not change it. */
  lts4NotMoreSaturated: true,
  /** Avoid against LTS 4: 13.2 CIEDE2000 under tritanopia (red against magenta), under the warm palette's 20 (the dash-dot, width and edge still differ). A ring does not change the lines. */
  avoidNearLts4: true,
  /**
   * The bike-facility rails against Avoid's magenta (2026-10-31): the protected lane's violet
   * (#a21caf) is 13.4 CIEDE2000 from it, under the rails' 15 (5.5 under protanopia). The rails'
   * pattern (the protected lane's blocks) and their place beside the line, not on it, still differ.
   */
  railsNearAvoid: ["protected"] as string[],
  /**
   * Avoid against LTS 4 in grey: the magenta and the red are 1.07:1 apart in luminance (2026-10-31),
   * under the 1.8:1 the warm palette keeps. Their edges (white and a near-black ring against a
   * near-black red), Avoid's dash-dot and its width tell them apart; in colour they are 30 CIEDE2000.
   */
  avoidLts4GreyUnderFloor: true,
  /** Avoid on the panels: none since 371's legend ring. */
  avoidOnDarkPanel: [] as string[],
} as const;
