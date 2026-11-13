/**
 * The live turn card on the Android lock screen (backlog 2026-11-13, "Phone in a pocket"): a glance at a locked phone on
 * the bars answers "what next and how far" without unlocking it. The phone app shows it as one silent notification,
 * updated in place (mobile/android/.../RideCuePlugin.java); this module only works out its words.
 *
 * It replaces the "Latest cue" notification, which kept the last sentence said, so "In 500 feet, turn left" sat there
 * after the turn. An app built before the plugin still shows that notification, with the card's words without the
 * distance (`still`), so it is never stale either.
 *
 * Nothing here is kept or sent; the card is cleared at End ride.
 */
import { cueSheet, cueShort, type Cue, type RideModel } from "./navigate.ts";
import { cardDistance } from "./format.ts";
import { t } from "./i18n.ts";

/** The arrow the card shows: a turn's movement, a flag at a stop or the end, else straight on. */
export type CardArrow = "left" | "right" | "bear_left" | "bear_right" | "uturn" | "stop" | "end" | "straight";

export interface TurnCard {
  /** The big line: the distance and the turn, "450 ft · Left". */
  title: string;
  /** The street, and the turn after it on a line of its own: "Church St NW\nThen in 0.3 mi · Right · R St NW". */
  body: string;
  /** The turn and street without a distance, for an older app's "Latest cue" (which cannot update in place). */
  still: string;
  arrow: CardArrow;
  /** The cue it leads with: a new one is a new card. */
  index: number;
}

function arrowOf(cue: Cue): CardArrow {
  if (cue.kind === "stop") return "stop";
  if (cue.kind === "end") return "end";
  return cue.movement ?? "straight";
}

/** "Left · Church St NW" as its turn and its street. */
function split(short: string): { turn: string; street: string } {
  const at = short.indexOf(" · ");
  return at < 0 ? { turn: short, street: "" } : { turn: short.slice(0, at), street: short.slice(at + 3) };
}

/**
 * The card at `progressM`: the next turn, stop or end ahead, as the cue sheet lists them (a jog's second turn is in the
 * first's words), and the one after. Null with nothing ahead, or before the first good fix.
 */
export function turnCard(model: RideModel, progressM: number | null): TurnCard | null {
  if (progressM === null) return null;
  const rows = cueSheet(model, progressM);
  const first = rows[0];
  if (!first) return null;
  const cue = model.cues.find((c) => c.index === first.index);
  if (!cue) return null;
  const short = cueShort(cue.rideText ?? cue.text);
  const { turn, street } = split(short);
  const lines = street ? [street] : [];
  const second = rows[1] && model.cues.find((c) => c.index === rows[1].index);
  if (second) {
    const after = t("Then in {distance}", { distance: cardDistance(second.atM - cue.atM) });
    lines.push(`${after} · ${cueShort(second.rideText ?? second.text)}`);
  }
  return {
    title: `${cardDistance(cue.atM - progressM)} · ${turn}`,
    body: lines.join("\n"),
    still: short,
    arrow: arrowOf(cue),
    index: cue.index,
  };
}

/**
 * Where the card counts from: the ride's place, or under weak GPS the reckoned one (estimateStep), held just short of the
 * next cue the ride has not passed. A reckoning that ran ahead never takes a turn off the card before a real fix
 * passes it (the voice still says the real "now" there too).
 */
export function cardAtM(model: RideModel, progressM: number | null, estM: number | undefined): number | null {
  if (progressM === null || estM === undefined) return progressM;
  const next = model.cues.find((c) => c.atM > progressM + 1);
  const limit = next ? next.atM - 2 : model.lengthM;
  return Math.max(progressM, Math.min(estM, limit));
}

/** A card with a sentence in place of the turn: off route, or a closure just ahead. No distance, so it is never stale. */
export function noteCard(text: string): TurnCard {
  return { title: text, body: "", still: text, arrow: "straight", index: -1 };
}
