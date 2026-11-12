// The cue bench (backlog 2026-11-12, item 3): rides a whole planned route on a made-up track and writes down every
// sentence Ride makes, when, and what the voice did with it (said, held behind another, cut off, dropped), then
// checks the cues against the line. Pure: the engine (navigate.ts step), the throttle (rideOutput.ts Announcer) and
// the voice (rideOutput.ts Voice) are the ride's own; only the clock, the speech and the GPS are made up.
//
// The tracks are synthetic: points along the planned line at a steady speed with a little seeded noise, never a
// rider's GPS. The routes are fixtures/cues/*.json (scripts/cue_bench_capture.py), made-up trips round junctions.
// Transcripts are kept in fixtures/cues/transcripts/; a change to them in a pull request shows every cue it touched.
import type { RouteResponse } from "./api.ts";
import { abbreviateStreet } from "./course.ts";
import { cueRows } from "./cueSheetPdf.ts";
import { haversineM, type LonLat } from "./geo.ts";
import {
  GPS_WEAK_SAID,
  PASSED_M,
  pointAt,
  rideModel,
  startState,
  step,
  weighFix,
  type Cue,
  type GpsWeakness,
  type RideEvent,
  type RideFix,
  type RideModel,
  type RideState,
  type Verbosity,
} from "./navigate.ts";
import { Announcer, Voice, type SpeechApi, type UtteranceLike } from "./rideOutput.ts";

export interface CueFixture {
  name: string;
  about: string;
  route: RouteResponse;
}

/** The bench's speeds: 8, 12 and 18 mph, a slow, an everyday and a fast rider (our default). */
export const BENCH_MPH = [8, 12, 18] as const;
const MPH = 0.44704;

/**
 * How fast the made-up voice speaks: 14 characters a second after 0.3 s to start (our default, unmeasured; about 160
 * words a minute, a phone voice at its normal rate).
 */
export const SPEECH_CHARS_S = 14;
export const SPEECH_START_S = 0.3;
/** A fix a second, as a phone's GPS gives (our default). */
export const FIX_S = 1;
/** The made-up GPS's error: up to this many metres off the line, seeded, and the accuracy it reports (our default). */
export const NOISE_M = 4;
export const ACCURACY_M = 8;

/** The first warning of a turn comes at least this long before it (backlog item 3's rule; our default). */
export const WARN_MIN_S = 8;
/** A turn whose line bends the other way by at least this much has its arrow on the wrong side (our default). */
export const SIDE_DEG = 30;
/** A bend this sharp in the line... */
export const BEND_DEG = 60;
/** ...with no cue this near is listed for a look (our default; a curve with no junction is a fair answer). */
export const BEND_CUE_M = 40;

export type Variant = "steady" | "missed-turn" | "weak-gps";

/** One sentence the engine made, and what the voice did with it. */
export interface Heard {
  /** Seconds from the start of the ride when the engine made it. */
  madeS: number;
  /** Metres along the line then. */
  atM: number;
  event: RideEvent;
  /** What the voice said, where it differs from what was made (a held cue said later with the distance then). */
  saidText?: string;
  startS?: number;
  endS?: number;
  /** Cut off by a newer sentence before its end. */
  cut?: boolean;
  /** Never said: replaced while it waited, or dropped as passed. */
  dropped?: boolean;
}

export interface Finding {
  rule: "missing" | "side" | "late" | "cut" | "after-passed" | "bend";
  cue: number | null;
  atM: number;
  words: string;
}

export interface BenchRun {
  fixture: string;
  mph: number;
  variant: Variant;
  model: RideModel;
  heard: Heard[];
  /** Notes about the ride itself (GPS weak), said through the throttle's note. */
  notes: { madeS: number; text: string }[];
  findings: Finding[];
}

/** A seeded random number in [0, 1) (mulberry32): the same track every run. */
export function seeded(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function seedOf(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

const R = 6371008.8;

/** A point `metres` from `p` on a bearing (degrees from north). */
export function moved(p: LonLat, bearingDeg: number, metres: number): LonLat {
  const b = (bearingDeg * Math.PI) / 180;
  const dLat = (metres * Math.cos(b)) / R;
  const dLon = (metres * Math.sin(b)) / (R * Math.cos((p[1] * Math.PI) / 180));
  return [p[0] + (dLon * 180) / Math.PI, p[1] + (dLat * 180) / Math.PI];
}

/** Degrees from north, a to b. */
export function bearingOf(a: LonLat, b: LonLat): number {
  const la = (a[1] * Math.PI) / 180;
  const lb = (b[1] * Math.PI) / 180;
  const dl = ((b[0] - a[0]) * Math.PI) / 180;
  const y = Math.sin(dl) * Math.cos(lb);
  const x = Math.cos(la) * Math.sin(lb) - Math.sin(la) * Math.cos(lb) * Math.cos(dl);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** The line's bend at `m`: its bearing over the `span` metres after, less the bearing over the `span` before; + is right. */
export function bendAt(model: RideModel, m: number, span = 25): number | null {
  if (m - span < 0 || m + span > model.lengthM) return null;
  const a = pointAt(model, m - span);
  const b = pointAt(model, m);
  const c = pointAt(model, m + span);
  if (haversineM(a, b) < span / 3 || haversineM(b, c) < span / 3) return null;
  return ((bearingOf(b, c) - bearingOf(a, b) + 540) % 360) - 180;
}

interface Track {
  fixes: RideFix[];
  /** Metres along the line the rider has reached at each fix, for the rules (the missed turn's stays at the turn). */
  alongM: number[];
}

/**
 * The made-up ride: a fix every FIX_S at a steady speed along the line, NOISE_M of seeded noise across it. "missed-turn"
 * rides straight on at the first plain turn and keeps going 250 m; "weak-gps" gives rough fixes (80 m) for 30 s from
 * the middle of the ride, as under trees.
 */
export function syntheticTrack(model: RideModel, speedMs: number, variant: Variant, seed: number, missAtM: number | null = null): Track {
  const rand = seeded(seed);
  const fixes: RideFix[] = [];
  const alongM: number[] = [];
  const weakFromS = model.lengthM / speedMs / 2;
  for (let s = 0; ; s += FIX_S) {
    let m = Math.min(model.lengthM, s * speedMs);
    let point: LonLat;
    let heading: number;
    if (variant === "missed-turn" && missAtM !== null && m > missAtM) {
      const before = pointAt(model, Math.max(0, missAtM - 20));
      const at = pointAt(model, missAtM);
      heading = bearingOf(before, at);
      point = moved(at, heading, m - missAtM);
      if (m - missAtM > 250) break;
      m = missAtM;
    } else {
      const a = pointAt(model, Math.max(0, m - 3));
      const b = pointAt(model, Math.min(model.lengthM, m + 3));
      heading = bearingOf(a, b);
      point = pointAt(model, m);
    }
    const across = (rand() * 2 - 1) * NOISE_M;
    point = moved(point, heading + 90, across);
    const weak = variant === "weak-gps" && s >= weakFromS && s < weakFromS + 30;
    fixes.push({ point, accuracyM: weak ? 80 : ACCURACY_M, speedMs, headingDeg: heading, at: s * 1000 });
    alongM.push(m);
    if (m >= model.lengthM) {
      // A few fixes standing at the end, so the arrival is said.
      for (let k = 1; k <= 5; k++) {
        fixes.push({ point, accuracyM: ACCURACY_M, speedMs: 0, headingDeg: null, at: (s + k * FIX_S) * 1000 });
        alongM.push(m);
      }
      break;
    }
  }
  return { fixes, alongM };
}

/** The made-up clock: timers the throttle, the voice and the speech set, run in order as the ride's time passes. */
class Clock {
  now = 0;
  private timers: { at: number; seq: number; fn: () => void }[] = [];
  private seq = 0;
  later(fn: () => void, ms: number): number {
    const id = ++this.seq;
    this.timers.push({ at: this.now + Math.max(0, ms), seq: id, fn });
    return id;
  }
  cancel(id: number): void {
    this.timers = this.timers.filter((t) => t.seq !== id);
  }
  /** Run every timer due by `to`, moving the clock to each. */
  runTo(to: number): void {
    for (;;) {
      this.timers.sort((a, b) => a.at - b.at || a.seq - b.seq);
      const next = this.timers[0];
      if (!next || next.at > to) break;
      this.timers.shift();
      this.now = next.at;
      next.fn();
    }
    this.now = to;
  }
}

/** The made-up speech: one sentence at a time, SPEECH_CHARS_S, ended by the clock; a cancel cuts it. */
class Speech implements SpeechApi {
  speaking = false;
  pending = false;
  private current: { u: UtteranceLike; timer: number } | null = null;
  private queue: UtteranceLike[] = [];
  private readonly clock: Clock;
  private readonly started: (u: UtteranceLike, at: number) => void;
  private readonly ended: (u: UtteranceLike, at: number, cut: boolean) => void;
  constructor(clock: Clock, started: (u: UtteranceLike, at: number) => void, ended: (u: UtteranceLike, at: number, cut: boolean) => void) {
    this.clock = clock;
    this.started = started;
    this.ended = ended;
  }
  speak(u: UtteranceLike): void {
    if (this.speaking) {
      this.queue.push(u);
      this.pending = true;
      return;
    }
    this.begin(u);
  }
  private begin(u: UtteranceLike): void {
    this.speaking = true;
    this.started(u, this.clock.now + SPEECH_START_S * 1000);
    const ms = (SPEECH_START_S + u.text.length / SPEECH_CHARS_S) * 1000;
    const timer = this.clock.later(() => {
      this.current = null;
      this.speaking = false;
      this.ended(u, this.clock.now, false);
      u.onend?.();
      const next = this.queue.shift();
      this.pending = this.queue.length > 0;
      if (next && !this.speaking) this.begin(next);
    }, ms);
    this.current = { u, timer };
  }
  cancel(): void {
    this.queue = [];
    this.pending = false;
    if (this.current) {
      this.clock.cancel(this.current.timer);
      this.ended(this.current.u, this.clock.now, true);
      this.current = null;
    }
    this.speaking = false;
  }
}

function isTurn(cue: Cue): boolean {
  return cue.kind === "turn" && cue.movement !== null;
}

/** The first plain left or right at least 300 m from either end: where "missed-turn" rides straight on. */
export function missedTurnAt(model: RideModel): number | null {
  const cue = model.cues.find(
    (c) => isTurn(c) && (c.movement === "left" || c.movement === "right") && !c.joined && !c.then?.length && c.atM > 300 && c.atM < model.lengthM - 300,
  );
  return cue ? cue.atM : null;
}

/** Ride one fixture once: the transcript's sentences and the rules' findings. */
export function benchRun(fixture: CueFixture, mph: number, variant: Variant = "steady", level: Verbosity = "full"): BenchRun {
  const model = rideModel(fixture.route);
  const speedMs = mph * MPH;
  const missAt = variant === "missed-turn" ? missedTurnAt(model) : null;
  const track = syntheticTrack(model, speedMs, variant, seedOf(`${fixture.name}/${mph}/${variant}`), missAt);
  const clock = new Clock();
  const heard: Heard[] = [];
  const notes: BenchRun["notes"] = [];
  // Which sentence each utterance said: by its words, the newest made first (a held cue is said with fresh words).
  const byText = new Map<string, Heard>();
  const speech = new Speech(
    clock,
    (u, at) => {
      const h = byText.get(u.text);
      if (h && h.startS === undefined) {
        h.startS = at / 1000;
        if (u.text !== h.event.spoken) h.saidText = u.text;
      }
    },
    (u, at, cut) => {
      const h = byText.get(u.text);
      if (h && h.startS !== undefined && h.endS === undefined) {
        if (cut && at / 1000 <= h.startS) {
          // Cancelled before a word of it was heard.
          h.startS = undefined;
          h.saidText = undefined;
          return;
        }
        h.endS = at / 1000;
        if (cut) h.cut = true;
      }
    },
  );
  const voice = new Voice({
    synth: speech,
    utterance: (text) => ({ text, lang: "", onend: null }),
    now: () => clock.now,
    later: (fn, ms) => void clock.later(fn, ms),
  });
  const announcer = new Announcer(
    (said) => voice.speak(said.text, said.urgent, said.after),
    () => clock.now,
    (fn, ms) => clock.later(fn, ms) as unknown as ReturnType<typeof setTimeout>,
    (timer) => clock.cancel(timer as unknown as number),
  );
  let state: RideState = startState();
  let weakness: GpsWeakness = { goodAt: 0, weak: false };
  for (let i = 0; i < track.fixes.length; i++) {
    const fix = track.fixes[i];
    clock.runTo(fix.at);
    const weighed = weighFix(weakness, fix.accuracyM, fix.at);
    weakness = { goodAt: weighed.goodAt, weak: weighed.weak };
    if (weighed.sayNow) {
      notes.push({ madeS: fix.at / 1000, text: GPS_WEAK_SAID });
      announcer.note(GPS_WEAK_SAID);
    }
    const out = step(model, state, fix, level);
    state = out.state;
    for (const event of out.events) {
      const h: Heard = { madeS: fix.at / 1000, atM: track.alongM[i], event };
      heard.push(h);
      byText.set(event.spoken, h);
      const respoken = event.respoken;
      const again =
        respoken &&
        (() => {
          const text = state.progressM === null ? event.spoken : respoken(state.progressM);
          if (text) byText.set(text, h);
          return text;
        });
      announcer.say(event.spoken, event.urgent, event.after, again);
    }
    if (variant === "missed-turn" && state.off) {
      // Off route found: the re-plan would take over from here.
      clock.runTo(fix.at + 10_000);
      break;
    }
  }
  clock.runTo(clock.now + 30_000);
  for (const h of heard) if (h.startS === undefined) h.dropped = true;
  const findings = variant === "steady" ? rules(model, heard, speedMs) : [];
  return { fixture: fixture.name, mph, variant, model, heard, notes, findings };
}

/** The bench's rules over one steady ride (backlog item 3). */
export function rules(model: RideModel, heard: readonly Heard[], speedMs: number): Finding[] {
  const out: Finding[] = [];
  const turns = model.cues.filter(isTurn);
  const said = (h: Heard) => h.startS !== undefined && !(h.cut && (h.endS ?? 0) - h.startS < 1);
  for (const cue of turns) {
    const arriveS = cue.atM / speedMs;
    // A jog's later turn is said early with the first (its head's `then`).
    const head = cue.joined ? [...turns].reverse().find((c) => c.atM < cue.atM && !c.joined) : undefined;
    // Its own warnings (not the "Continue on ..." said after it, which has no phase), and a jog head's early ones.
    const mine = heard.filter(
      (h) => h.event.phase !== undefined && h.event.cue && (h.event.cue.index === cue.index || (head && h.event.cue.index === head.index && h.event.phase !== "now")),
    );
    const before = mine.filter((h) => said(h) && (h.startS ?? Infinity) <= arriveS + PASSED_M / speedMs);
    const words = cue.text;
    if (!before.length) {
      out.push({ rule: "missing", cue: cue.index, atM: cue.atM, words: `${words} was never said before the turn` });
    } else {
      const first = Math.min(...before.map((h) => h.startS ?? Infinity));
      const lead = arriveS - first;
      const prev = [...turns].reverse().find((c) => c.atM < cue.atM);
      const room = Math.min(cue.atM, prev ? cue.atM - prev.atM : Infinity) / speedMs;
      if (lead < WARN_MIN_S && room >= WARN_MIN_S + 2 && !cue.joined) {
        out.push({ rule: "late", cue: cue.index, atM: cue.atM, words: `${words} first said ${lead.toFixed(1)} s before the turn` });
      }
    }
    for (const h of mine) {
      if (h.startS !== undefined && h.startS > arriveS + PASSED_M / speedMs && h.event.cue?.index === cue.index) {
        out.push({ rule: "after-passed", cue: cue.index, atM: cue.atM, words: `"${h.saidText ?? h.event.spoken}" said ${(h.startS * speedMs - cue.atM).toFixed(0)} m past the turn` });
      }
    }
    const plain = !cue.cross && !cue.across && !cue.over && !cue.exit && !cue.junction && cue.movement !== "uturn";
    const bend = plain ? bendAt(model, cue.atM) : null;
    if (bend !== null && cue.movement) {
      const right = cue.movement === "right" || cue.movement === "bear_right";
      if ((right && bend <= -SIDE_DEG) || (!right && bend >= SIDE_DEG)) {
        out.push({ rule: "side", cue: cue.index, atM: cue.atM, words: `${words} but the line bends ${bend > 0 ? "right" : "left"} ${Math.abs(bend).toFixed(0)} degrees there` });
      }
    }
  }
  // A sentence cut off by one about another cue or the ride (two cues on top of each other); a cue's "now" cutting
  // its own warning short is the plan (the turn is what matters then).
  for (const h of heard) {
    if (!h.cut || h.startS === undefined || !h.event.cue) continue;
    const by = heard.find((o) => o !== h && o.startS !== undefined && Math.abs(o.startS - (h.endS ?? 0) - SPEECH_START_S) < 0.01);
    if (by && by.event.cue?.index === h.event.cue.index) continue;
    const what = by ? (by.event.cue ? `#${by.event.cue.index}'s ${by.event.phase ?? "sentence"}` : by.event.kind) : "another sentence";
    out.push({ rule: "cut", cue: h.event.cue.index, atM: h.event.cue.atM, words: `"${h.saidText ?? h.event.spoken}" cut off ${((h.endS ?? 0) - h.startS).toFixed(1)} s in by ${what}` });
  }
  // Sharp bends in the line with no cue near: listed for a look (a curve with no junction is a fair answer).
  const cued = model.cues.filter((c) => c.kind !== "stop" && c.kind !== "end").map((c) => c.atM);
  let lastBend = -Infinity;
  for (let i = 1; i < model.coordinates.length - 1; i++) {
    const m = model.along[i];
    if (m - lastBend < 50) continue;
    const bend = bendAt(model, m, 20);
    if (bend === null || Math.abs(bend) < BEND_DEG) continue;
    lastBend = m;
    if (cued.some((c) => Math.abs(c - m) <= BEND_CUE_M)) continue;
    out.push({ rule: "bend", cue: null, atM: m, words: `the line bends ${bend > 0 ? "right" : "left"} ${Math.abs(bend).toFixed(0)} degrees with no cue within ${BEND_CUE_M} m` });
  }
  return out.sort((a, b) => a.atM - b.atM || a.rule.localeCompare(b.rule));
}

function cueLabel(cue: Cue | undefined): string {
  if (!cue) return "";
  const kind = cue.movement ?? cue.kind;
  return `#${cue.index} ${kind}${cue.street ? ` ${abbreviateStreet(cue.street)}` : ""}`;
}

function outcome(h: Heard): string {
  if (h.dropped) return "dropped";
  const start = h.startS ?? 0;
  const held = start - h.madeS - SPEECH_START_S;
  const parts = [held > 0.05 ? `held ${held.toFixed(1)} s` : "said"];
  if (h.cut) parts.push(`cut ${((h.endS ?? start) - start).toFixed(1)} s in`);
  if (h.saidText) parts.push(`as "${h.saidText}"`);
  return parts.join(", ");
}

/** One ride as text: a line a sentence, then the findings. Stable: the same build gives the same words. */
export function transcript(run: BenchRun): string {
  const lines = [`## ${run.fixture} at ${run.mph} mph, ${run.variant}`];
  const rows: { s: number; line: string }[] = [];
  for (const h of run.heard) {
    const e = h.event;
    const what = e.kind === "cue" ? `${cueLabel(e.cue)} ${e.phase}` : e.kind;
    rows.push({ s: h.madeS, line: `${h.madeS.toFixed(0).padStart(5)} s ${h.atM.toFixed(0).padStart(6)} m  ${what}${e.urgent ? " (urgent)" : ""}: "${e.spoken}" -> ${outcome(h)}` });
  }
  for (const n of run.notes) rows.push({ s: n.madeS, line: `${n.madeS.toFixed(0).padStart(5)} s ${"".padStart(6)}    note: "${n.text}"` });
  rows.sort((a, b) => a.s - b.s);
  lines.push(...rows.map((r) => r.line));
  if (run.variant === "missed-turn") {
    const off = run.heard.find((h) => h.event.kind === "off-route");
    const missAt = missedTurnAt(run.model) ?? 0;
    lines.push(off ? `  off route said ${(off.madeS * run.mph * MPH - missAt).toFixed(0)} m past the missed turn` : "  ! off route never said after the missed turn");
  }
  for (const f of run.findings) lines.push(`  ! ${f.rule} at ${f.atM.toFixed(0)} m${f.cue !== null ? ` (#${f.cue})` : ""}: ${f.words}`);
  return lines.join("\n");
}

/** A fixture's whole transcript: the steady rides at each speed, then a missed turn and weak GPS at 12 mph. */
export function fixtureTranscript(fixture: CueFixture): { text: string; runs: BenchRun[] } {
  const runs = [
    ...BENCH_MPH.map((mph) => benchRun(fixture, mph, "steady")),
    ...(missedTurnAt(rideModel(fixture.route)) !== null ? [benchRun(fixture, 12, "missed-turn")] : []),
    benchRun(fixture, 12, "weak-gps"),
  ];
  const head = [`# ${fixture.name}: ${fixture.about}`, "", "## The cues Ride made", ...cueList(runs[0].model)].join("\n");
  return { text: [head, ...runs.map(transcript)].join("\n\n") + "\n", runs };
}

function cueList(model: RideModel): string[] {
  return model.cues.map((c) => `${c.atM.toFixed(0).padStart(6)} m  ${cueLabel(c)}${c.joined ? " (joined)" : ""}: ${c.rideText ?? c.text}`);
}

/**
 * The shared cue rows (backlog item 11.7): what the phone images, the cue sheet and the strip list for this route
 * (cueSheetPdf.ts cueRows, the strip), kept as fixtures/cues/expected/<name>.json; the connector's cue cards
 * (src/core/cue_cards.py cue_rows) are tested against the same file.
 */
export interface SharedRow {
  turn: string;
  road: string;
  then: string;
  arrow: string;
}

export function sharedRows(fixture: CueFixture): SharedRow[] {
  return cueRows(fixture.route, "strip").map((r) => ({
    turn: r.turn,
    road: r.road ? abbreviateStreet(r.road) : "",
    then: r.then,
    arrow: arrowKey(r.arrow as unknown as Record<string, unknown>),
  }));
}

/** An arrow as a short key: "turn left,right", "turn across right", "cross", "stop 1". */
export function arrowKey(arrow: Record<string, unknown>): string {
  const kind = String(arrow.kind);
  if (kind === "turn") return `turn${arrow.across ? " across" : ""} ${(arrow.moves as string[]).join(",")}`;
  if (kind === "stop") return `stop ${arrow.number ?? ""}`.trim();
  return kind;
}

