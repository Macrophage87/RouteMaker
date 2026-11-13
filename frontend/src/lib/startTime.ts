/**
 * Plan's day and start time (backlog after v0.26.0, item 1; the owner, 2026-11-13: "Plan only", Go always plans from
 * now). The rider picks a day and clock time in When; the route is planned for it (the API's `depart_at`: the ride
 * time of that moment where no other is chosen, the closures in force then, a transit trip's timetable for that day),
 * and the light marks and the arrival clock are for leaving then.
 *
 * The time is kept as the region's wall clock, "YYYY-MM-DDTHH:MM" (what a datetime-local box holds), in Washington's
 * time whatever the device's zone, and sent so: the API reads a time without an offset as Washington's. It stays on
 * the page, never in a link or a saved route: when someone rides is theirs.
 */
import { clockLocale, t } from "./i18n.ts";
import { usesBikeshare, type PresetId } from "./presets.ts";

const ZONE = "America/New_York";
/** As the API's WHEN_RANGE (core.api), a day short so a time picked late at night is still inside it. */
const RANGE_DAYS = 365;
const WALL = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

/**
 * Every ride type but Bikeshare and Rebalance Ride, which plan from the docks as they are now (the API refuses a
 * start time on them).
 */
export function offersStartTime(preset: PresetId): boolean {
  return !usesBikeshare(preset);
}

/** The region's wall clock at `ms`, as "YYYY-MM-DDTHH:MM". */
export function wallClock(ms: number): string {
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(ms))
      .map((p) => [p.type, p.value]),
  );
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

/** The moment a wall-clock time in the region is, or null for text that is not one. */
export function startMs(wall: string | undefined | null): number | null {
  const m = wall ? WALL.exec(wall) : null;
  if (!m) return null;
  const [year, month, day, hour, minute] = m.slice(1).map(Number);
  const asked = m[0];
  const asUtc = Date.UTC(year, month - 1, day, hour, minute);
  if (Number.isNaN(asUtc)) return null;
  // The zone's offset (wall clock less UTC) a day before and a day after: the earlier where it gives this wall clock
  // (a repeated hour in November is its first), else the later; an hour skipped in March takes the earlier, as the
  // API's Python reads it (fold 0), so page and plan agree.
  const offset = (ms: number) => Date.parse(`${wallClock(ms)}:00Z`) - ms;
  const before = asUtc - offset(asUtc - 86_400_000);
  if (wallClock(before) === asked) return before;
  const after = asUtc - offset(asUtc + 86_400_000);
  return wallClock(after) === asked ? after : before;
}

/** Our default when the rider first picks Leave at (unmeasured): the next whole hour. */
export function defaultStart(nowMs: number): string {
  const hour = 3_600_000;
  return wallClock(Math.ceil((nowMs + 1) / hour) * hour);
}

/** The datetime-local box's bounds: from now to a year on. */
export function startBounds(nowMs: number): { min: string; max: string } {
  return { min: wallClock(nowMs), max: wallClock(nowMs + RANGE_DAYS * 86_400_000) };
}

/** A start time the API takes: a real time within the year ahead (a past one is now's, and is dropped). */
export function fitStart(wall: string | undefined | null, nowMs: number): string | undefined {
  const ms = startMs(wall);
  if (ms === null || ms < nowMs - 60_000 || ms > nowMs + RANGE_DAYS * 86_400_000) return undefined;
  return wall as string;
}

/** A start in a few words, in the region's time: "Sat, Nov 15, 8:00 AM". */
export function startShort(ms: number, locale?: string): string {
  return new Intl.DateTimeFormat(locale ?? clockLocale(), {
    timeZone: ZONE,
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(ms));
}

/** The arrival as a screen reader hears it with a start set, "{start}" as startShort says it (Plan only; English and Spanish, as Plan's words are). */
export function startArrivalSaid(time: string, start: string): string {
  return t("arriving about {time} if you leave {start}", { time, start });
}
