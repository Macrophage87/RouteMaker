/**
 * The planner's figures as a screen reader says them (the a11y review's a11y-6: "mi", "h" and a bare "m" were read as
 * letters or as minutes): the same figures as lib/format.ts formatDistance, formatDuration and formatClimb, the units
 * in words, US units first and metric in brackets. Ride's own speech is lib/format.ts spokenDistance (US units only).
 *
 * Plain data in, plain data out, so node --test runs all of it.
 */
import { FEET_BELOW_M, FEET_PER_METRE, formatDistance, milesFigure } from "./format.ts";
import { t } from "./i18n.ts";

const DASH = "–";

function usable(value: number): boolean {
  return Number.isFinite(value) && value >= 0;
}

/** Whole units, or to the nearest ten from a hundred up, as formatDistance rounds them. */
function roundShort(value: number): number {
  return value >= 100 ? Math.round(value / 10) * 10 : Math.round(value);
}

function feetSpoken(feet: string, meters: string): string {
  return feet === "1" ? t("1 foot ({meters} meters)", { meters }) : t("{feet} feet ({meters} meters)", { feet, meters });
}

/** "12.3 miles (19.8 kilometers)"; below a tenth of a mile "500 feet (150 meters)", as formatDistance shows it. */
export function formatDistanceSpoken(metres: number): string {
  if (!usable(metres)) return formatDistance(metres);
  if (metres < FEET_BELOW_M) return feetSpoken(String(roundShort(metres * FEET_PER_METRE)), String(roundShort(metres)));
  const miles = milesFigure(metres);
  const km = (metres / 1000).toFixed(1);
  return miles === "1.0" ? t("1 mile ({km} kilometers)", { km }) : t("{miles} miles ({km} kilometers)", { miles, km });
}

/** "45 minutes", "1 hour", "1 hour 5 minutes", "2 hours 30 minutes": formatDuration's figure, in words. */
export function formatDurationSpoken(seconds: number): string {
  if (!usable(seconds)) return DASH;
  const total = Math.max(1, Math.round(seconds / 60));
  const hours = Math.floor(total / 60);
  const minutes = total % 60;
  const minutesSaid = minutes === 1 ? t("1 minute") : t("{n} minutes", { n: minutes });
  if (hours === 0) return minutesSaid;
  const hoursSaid = hours === 1 ? t("1 hour") : t("{n} hours", { n: hours });
  return minutes === 0 ? hoursSaid : `${hoursSaid} ${minutesSaid}`;
}

/** A climb or an elevation: "340 feet (104 meters)", "2,930 feet (893 meters)", as formatClimb shows it. */
export function formatClimbSpoken(metres: number): string {
  if (!usable(metres)) return DASH;
  return feetSpoken(Math.round(metres * FEET_PER_METRE).toLocaleString("en-US"), Math.round(metres).toLocaleString("en-US"));
}
