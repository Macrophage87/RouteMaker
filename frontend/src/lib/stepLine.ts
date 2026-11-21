/**
 * Directions' one-line steps (intuitiveness review, 2026-11-21: "Directions, 65 steps" was a 3.5-screen wall of
 * 97-character sentences): a stretch as its turn and street, its length in the rider's one unit, and its level as the
 * colour chip, said in words only from LTS 3 up. "Full detail" shows the API's whole sentences as before.
 */
import type { DescriptionEntry } from "./api.ts";
import { cardDistance } from "./format.ts";
import { t } from "./i18n.ts";
import { isUnnamed, turnWords, wayWords } from "./navigate.ts";
import { stressSegments, type BarKey } from "./stressBar.ts";

/** A level's key in the stress bar: "2.5" is the half step after 2. */
export function tierKey(tier: number): BarKey {
  return (Number.isInteger(tier) ? String(tier) : `${Math.floor(tier)}h`) as BarKey;
}

export interface StepLine {
  /** "Bear left onto New Hampshire Avenue Northwest", "Rock Creek Trail". */
  words: string;
  /** "190 ft", "0.4 mi". */
  distance: string;
  /** The stretch's level, for its chip; null where not rated. */
  tier: number | null;
  /** Said in words: from LTS 3 up, and a junction marked higher stress. */
  warn: string | null;
}

const noStop = (text: string) => text.replace(/\.$/, "");

/** A stretch's one line; null for any other entry (a junction, a stop, a closure, a climb), which keeps its sentence. */
export function stepLine(entry: DescriptionEntry): StepLine | null {
  if (entry.kind !== "stretch") return null;
  const turn = entry.turn;
  // A circle's exit and a crossing before a turn keep their whole sentence (the owner, 2026-10-20 and 2026-10-24).
  if (turn?.exit || turn?.across) return null;
  const street = turn?.onto ?? entry.street;
  let words: string | null = null;
  if (turn?.cross) words = noStop(t("Cross {road}.", { road: turn.cross }));
  else if (turn?.movement && turn.movement !== "straight") {
    words = noStop(turnWords(turn.movement, street, turn.stay === true, turn.exit ?? null, turn.toward ?? null));
  } else if (street && !/^this part of the route$/i.test(street.trim())) {
    // "The path" for a path with no name, as a sentence starts.
    const way = isUnnamed(street) && /path/i.test(street) ? wayWords("path") : wayWords(street);
    words = way.charAt(0).toLocaleUpperCase() + way.slice(1);
  }
  if (!words) return null;
  const tier = entry.tier;
  // The level as the bar names it ("LTS 3", "LTS 3.5", "Avoid").
  const busy = tier !== null && tier >= 3 ? (stressSegments({ [tierKey(tier)]: 1 }).find((s) => s.key === tierKey(tier))?.short ?? null) : null;
  const junction = turn?.severity === "red" || turn?.severity === "orange" ? t("busy junction") : null;
  const unpaved = entry.surface ? t("unpaved") : null;
  const warn = [busy, junction, unpaved].filter(Boolean).join(", ") || null;
  return { words, distance: cardDistance(entry.to_m - entry.from_m), tier, warn };
}
