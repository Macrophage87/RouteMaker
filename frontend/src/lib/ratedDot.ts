/**
 * A rated junction's level as its colour and its words, apart from lib/intersectionMarkers.ts so Ride can use them
 * without that module's Plan phrases.
 */
import { HALF_PALETTES, PALETTES, currentPalette } from "../stressStyle.js";
import { t } from "./i18n.ts";

/**
 * A junction the raters rated is a dot in its level's stress colour, the map's own (the owner,
 * 2026-11-15: "I like 2", a dot at each crossing rated 3 or more, the line keeping its riding level;
 * "The junction should be clickable"). The dot is small and colour only (the owner,
 * 2026-11-20: "Just colors as small dots"); its level is in the words of its panel and its list row. The junctions the model prices keep the triangle and the diamond.
 */
export function ratedLevelText(level: number): string {
  return level >= 5 ? t("Avoid") : `LTS ${level}`;
}

/** The dot's fill for a level in a palette (a half step's own colour where the palette has one, else its lower level's). */
export function ratedDotFill(level: number, palette: string = currentPalette()): string {
  const whole = Math.min(5, Math.max(1, Math.floor(level)));
  const palettes = PALETTES as Record<string, Record<number, { color: string }>>;
  const halves = HALF_PALETTES as Record<string, Record<number, { color: string }> | undefined>;
  const own = palettes[palette] ?? palettes.twotone;
  if (level > whole && whole < 5) return halves[palette]?.[whole]?.color ?? own[whole].color;
  return own[whole].color;
}
