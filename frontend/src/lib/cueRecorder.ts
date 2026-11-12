/**
 * The ride's cue log, a "flight recorder" (backlog 2026-11-12, item 3): what Ride made of each cue and what the voice did
 * with it, so a cue that was not heard can be explained ("cue 14 was made, held behind another, then dropped") instead
 * of guessed at: an earlier report of a turn not said could not be told apart from stuck speech without it.
 *
 * Privacy: kept in this page's memory only, for this ride; nothing is sent or stored. A line holds the cue's number in
 * the ride's list, its kind and phase, metres to it, a GPS quality word and seconds since the ride started: never a
 * place, a street's name, a sentence's words or a time of day. Its text goes where the rider pastes it, beside the plan
 * link they choose to share; the cue bench (lib/cueBench.ts) rides that plan and gives the same cue numbers.
 */
import type { Phase, RideEvent } from "./navigate.ts";

/** How many lines are kept, oldest dropped first (our default, unmeasured: about an hour's riding in town). */
export const CUE_LOG_KEPT = 400;

/** A fix this good or better is "good", up to POOR_FIX_M (navigate.ts) "fair", rougher "poor" (our default, unmeasured). */
export const GOOD_FIX_M = 20;
const POOR_FIX_M = 50;

/** What the voice did with a sentence (lib/rideOutput.ts Voice and Announcer). */
export type VoiceTrace = "said" | "waits" | "replaced" | "cut" | "stuck" | "dropped";

export interface CueLogLine {
  /** Whole seconds since the ride started. */
  s: number;
  /** What happened: "made" by the engine, a VoiceTrace, or a ride event (off route, back on, a re-plan, weak GPS). */
  what: string;
  /** The cue it is about: its number, kind (a turn's movement) and phase; absent for a ride event. */
  cue?: string;
  /** Metres to the cue when it was made, rounded to 5. */
  toM?: number;
  /** The fix it was made on: good, fair or poor. */
  fix?: "good" | "fair" | "poor";
}

function fixWord(accuracyM: number): "good" | "fair" | "poor" {
  const a = accuracyM > 0 ? accuracyM : 0;
  return a <= GOOD_FIX_M ? "good" : a <= POOR_FIX_M ? "fair" : "poor";
}

/** "#5 left prepare" and "#5 left now": the same cue. */
function sameCue(a: string | undefined, b: string | undefined): boolean {
  return !!a && !!b && a.split(" ")[0] === b.split(" ")[0];
}

function cueWord(event: Pick<RideEvent, "cue" | "phase" | "kind">): string {
  const cue = event.cue;
  if (!cue) return event.kind;
  const phase: Phase | "after" = event.phase ?? "after";
  return `#${cue.index} ${cue.movement ?? cue.kind} ${phase}`;
}

export class CueRecorder {
  private kept: CueLogLine[] = [];
  private startedAt: number | null = null;
  /** Which cue each sentence was made for, by its words (never kept in a line). */
  private bySentence = new Map<string, string>();

  /** A new ride (or a restart): the log starts again from nothing. */
  start(now: number): void {
    this.kept = [];
    this.bySentence.clear();
    this.startedAt = now;
  }

  /** Whether a ride is under way (between start and end): the crash report carries the log only then. */
  get started(): boolean {
    return this.startedAt !== null;
  }

  /** The ride ended: nothing more is kept; the lines stay for the ride summary until the next ride starts. */
  end(): void {
    this.startedAt = null;
  }

  /** The engine made a cue's sentence (navigate.ts step's events). */
  made(event: RideEvent, progressM: number | null, accuracyM: number, now: number): void {
    if (this.startedAt === null) return;
    if (event.kind !== "cue") {
      this.push({ s: this.since(now), what: event.kind });
      this.remember(event.spoken, event.kind);
      return;
    }
    const cue = cueWord(event);
    this.remember(event.spoken, cue);
    const toM = event.cue && progressM !== null ? Math.round((event.cue.atM - progressM) / 5) * 5 : undefined;
    this.push({ s: this.since(now), what: "made", cue, ...(toM !== undefined ? { toM } : {}), fix: fixWord(accuracyM) });
  }

  /** A held cue said with fresh words (rideOutput.ts Announcer's `again`): the same cue. */
  alias(sentence: string, as: string): void {
    const cue = this.bySentence.get(as);
    if (cue) this.remember(sentence, cue);
  }

  /** A note about the ride itself (GPS weak, paused). */
  note(what: string, now: number): void {
    if (this.startedAt === null) return;
    this.push({ s: this.since(now), what });
  }

  /** What the voice or the throttle did with a sentence. */
  voice(what: VoiceTrace, sentence: string, now: number): void {
    if (this.startedAt === null) return;
    this.push({ s: this.since(now), what, cue: this.bySentence.get(sentence) ?? "note" });
  }

  /**
   * Whether a cue went wrong this ride: one dropped unsaid, replaced while it waited, cut off by another cue's or the
   * ride's sentence, or stuck. The ride summary offers the log only then (the owner, 2026-11-12: "Only when a cue went
   * wrong"). A cue's own "now" cutting its warning is the plan, not a fault, and is not counted.
   */
  wentWrong(): boolean {
    return this.kept.some((l, i) => {
      if (l.cue === undefined || l.cue === "note") return false;
      if (l.what === "dropped" || l.what === "replaced" || l.what === "stuck") return true;
      // Cut: by the sentence said next (the voice cuts, then starts the newer one).
      const by = l.what === "cut" ? this.kept.slice(i + 1).find((n) => n.what === "said") : undefined;
      return l.what === "cut" && !sameCue(l.cue, by?.cue);
    });
  }

  lines(): readonly CueLogLine[] {
    return this.kept;
  }

  /** The log as plain text, oldest first: "+123 s  #5 left prepare  made  to_m=49  good". */
  text(): string {
    if (!this.kept.length) return "";
    const rows = this.kept.map((l) => {
      const parts = [`+${l.s} s`.padStart(8), l.cue ?? "", l.what];
      if (l.toM !== undefined) parts.push(`to_m=${l.toM}`);
      if (l.fix) parts.push(l.fix);
      return parts.filter(Boolean).join("  ");
    });
    return ["Cue log (this ride; cue numbers as in the plan's list, no places):", ...rows].join("\n");
  }

  private since(now: number): number {
    return Math.max(0, Math.round((now - (this.startedAt ?? now)) / 1000));
  }

  private push(line: CueLogLine): void {
    this.kept.push(line);
    if (this.kept.length > CUE_LOG_KEPT) this.kept.splice(0, this.kept.length - CUE_LOG_KEPT);
  }

  /** Which cue a sentence is, the oldest forgotten past CUE_LOG_KEPT sentences. */
  private remember(sentence: string, cue: string): void {
    this.bySentence.delete(sentence);
    this.bySentence.set(sentence, cue);
    while (this.bySentence.size > CUE_LOG_KEPT) {
      const first = this.bySentence.keys().next().value;
      if (first === undefined) break;
      this.bySentence.delete(first);
    }
  }
}

/** The page's one log: Ride writes it, the ride summary and the crash report read it. */
export const rideCueLog = new CueRecorder();
