/**
 * The ride time the map follows: the one chosen in the panel, or for "when I'm
 * planning" the setting of the moment, worked out as the API does
 * (routemaker.ridetime.when_at): night is 21:00 to 07:00 on any day, the
 * weekend is Saturday, Sunday and the US federal holidays, rush hours are
 * Monday to Friday 07:00-10:00 and 16:00-19:00, all in the region's time. The map reads it for the roads closed
 * to cars at set times (the owner, 2026-09-29: "Path on weekends only"),
 * which draw as off-road paths in the ride times they are closed in.
 */
import type { When } from "./dials.ts";

const ZONE = "America/New_York";
const RUSH_WINDOWS: ReadonlyArray<[number, number]> = [
  [7 * 60, 10 * 60],
  [16 * 60, 19 * 60],
];
const NIGHT_START = 21 * 60;
const NIGHT_END = 7 * 60;

/** A calendar date as "YYYY-MM-DD". */
function iso(year: number, month: number, day: number): string {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

/** Day of the week, Monday 0, of a calendar date. */
function weekday(year: number, month: number, day: number): number {
  return (new Date(Date.UTC(year, month - 1, day)).getUTCDay() + 6) % 7;
}

function nthWeekday(year: number, month: number, wd: number, n: number): string {
  const first = weekday(year, month, 1);
  return iso(year, month, 1 + ((wd - first + 7) % 7) + 7 * (n - 1));
}

function lastWeekday(year: number, month: number, wd: number): string {
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const last = weekday(year, month, days);
  return iso(year, month, days - ((last - wd + 7) % 7));
}

function observed(year: number, month: number, day: number): string {
  const wd = weekday(year, month, day);
  const shift = wd === 5 ? -1 : wd === 6 ? 1 : 0;
  const d = new Date(Date.UTC(year, month - 1, day + shift));
  return iso(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate());
}

/** The eleven US federal holidays of `year`, as observed (5 U.S.C. 6103). */
export function federalHolidays(year: number): Set<string> {
  return new Set([
    observed(year, 1, 1),
    observed(year, 6, 19),
    observed(year, 7, 4),
    observed(year, 11, 11),
    observed(year, 12, 25),
    nthWeekday(year, 1, 0, 3), // Birthday of Martin Luther King, Jr.
    nthWeekday(year, 2, 0, 3), // Washington's Birthday
    lastWeekday(year, 5, 0), // Memorial Day
    nthWeekday(year, 9, 0, 1), // Labor Day
    nthWeekday(year, 10, 0, 2), // Columbus Day
    nthWeekday(year, 11, 3, 4), // Thanksgiving Day
  ]);
}

/** The setting a moment falls in, read in the region's time. */
export function whenAt(moment: Date): When {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: ZONE,
      year: "numeric",
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "numeric",
      hourCycle: "h23",
    })
      .formatToParts(moment)
      .map((p) => [p.type, p.value]),
  );
  const [year, month, day] = [Number(parts.year), Number(parts.month), Number(parts.day)];
  const minute = Number(parts.hour) * 60 + Number(parts.minute);
  if (minute >= NIGHT_START || minute < NIGHT_END) return "night";
  if (weekday(year, month, day) >= 5 || federalHolidays(year).has(iso(year, month, day))) return "weekend";
  return RUSH_WINDOWS.some(([start, end]) => start <= minute && minute < end) ? "weekday_rush" : "weekday_offpeak";
}

/** The ride time the map follows: the one chosen, or the setting of `now`. */
export function mapWhen(chosen: When | null, now: Date = new Date()): When {
  return chosen ?? whenAt(now);
}
