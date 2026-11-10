/**
 * The cue sheet as a phone lock-screen image (the owner, 2026-10-16: "a lot of people take pictures of them on their
 * phones and use them as lock screens"): a portrait PNG drawn in the browser (app/lockScreenRender.ts), 1179 by 2556
 * pixels (an iPhone Pro's screen; an Android phone fits it to its own), in large type like the handlebar strip.
 *
 * This module is the layout alone, pure, so it is tested without a canvas: every line of text with its place, size
 * and weight, given a `measure` for text widths. The top 20% is left clear for the lock screen's clock and the
 * bottom 7% for its controls (our default, tightened 2026-11-10 at the owner's "There's plenty of white space"); the route's name and distance sit small just under the top band and the credits
 * small just above the bottom one. The rows are the strip's (cueSheetPdf.ts cueRows "strip"): the miles from the
 * cue before large in the rider's units alone, the miles since the start on the right, the cue's picture (an arrow for a turn,
 * lib/cueArrow.ts: the owner, 2026-11-10, "Basically show the arrows"), then the turn with a caution's reason small, the road abbreviated, and a jog's later turns. Stops
 * are rows of their own, by name where the plan names them. Where the cues do not fit on one image, each leg gets its
 * own: the start or a stop at its top, the next stop or the finish at its bottom (so a stop ends one image and heads
 * the next), and a leg too long for one image runs on to the next, "Part 2 of 3". Dark text on white. No place is named (exportName) but a stop the rider named, so never a Home.
 */
import type { RouteResponse } from "./api.ts";
import { abbreviateStreet } from "./course.ts";
import type { CueArrow } from "./cueArrow.ts";
import { creditLine } from "./course.ts";
import { cueRows, summaryLine, type CueRow } from "./cueSheetPdf.ts";
import { CREATOR } from "./gpx.ts";
import { markerFigure } from "./format.ts";
import { metricFirst } from "./units.ts";
import { exportFileName, exportName } from "./gpxText.ts";

export const LOCK_WIDTH = 1179;
export const LOCK_HEIGHT = 2556;
/** The lock screen's own clock and widgets above, its controls below: no cue is drawn in either band. */
export const CLEAR_TOP = Math.round(LOCK_HEIGHT * 0.2);
export const CLEAR_BOTTOM = Math.round(LOCK_HEIGHT * 0.07);
export const INK = "#111111";
export const PAPER = "#ffffff";

const SIDE = 56;
const PAD = 10;
const COLUMNS = { miles: 230, arrow: 140, total: 170 } as const;
/** The cue's picture: a square this wide, its top at the row's top and PAD. */
export const ARROW_PX = 108;
const PX = { title: 36, summary: 26, part: 28, miles: 80, unit: 26, turn: 56, reason: 28, road: 50, then: 32, total: 36, credit: 36 } as const;

export type Weight = 400 | 700;
/** The width in pixels of `text` at `px` in the image's face (the canvas's measureText in the browser). */
export type Measure = (text: string, px: number, weight: Weight) => number;

export interface LockLine {
  text: string;
  x: number;
  /** The baseline. */
  y: number;
  px: number;
  weight: Weight;
}

export interface LockPage {
  /** "Part 1 of 3", or null on a single image. */
  part: string | null;
  lines: LockLine[];
  /** The rules under each row, by y. */
  rules: number[];
  /** How many cues are on this image. */
  cues: number;
  /** Each cue's picture: its box's top left corner and its width (ARROW_PX), in pixels. */
  arrows: { x: number; y: number; size: number; arrow: CueArrow }[];
  /** Where the cues may be drawn, top and bottom, for the tests and the renderer's own check. */
  cueTop: number;
  cueBottom: number;
}

type LockRoute = Parameters<typeof cueRows>[0];

/** `text` broken into lines no wider than `width`, at spaces, a word too long cut by characters. */
export function wrapPx(text: string, px: number, weight: Weight, width: number, measure: Measure): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.trim().split(/\s+/).filter(Boolean)) {
    const tried = line ? `${line} ${word}` : word;
    if (measure(tried, px, weight) <= width) {
      line = tried;
      continue;
    }
    if (line) lines.push(line);
    let rest = Array.from(word);
    line = "";
    while (measure(rest.join(""), px, weight) > width) {
      let n = rest.length - 1;
      while (n > 1 && measure(rest.slice(0, n).join(""), px, weight) > width) n -= 1;
      n = Math.max(1, n);
      lines.push(rest.slice(0, n).join(""));
      rest = rest.slice(n);
    }
    line = rest.join("");
  }
  if (line) lines.push(line);
  return lines;
}

/** A row's lines relative to its top, and its height. */
function rowLines(row: CueRow, sinceM: number, measure: Measure): { lines: LockLine[]; height: number } {
  const lines: LockLine[] = [];
  const column = (x: number, width: number, parts: { text: string; px: number; weight: Weight; whole?: boolean }[]) => {
    let y = PAD;
    for (const part of parts) {
      // The miles are never broken: "123." over "4" would misread at a glance.
      for (const text of part.whole ? [part.text] : wrapPx(part.text, part.px, part.weight, width - PAD, measure)) {
        y += Math.round(part.px * 1.15);
        lines.push({ text, x, y: y - Math.round(part.px * 0.2), px: part.px, weight: part.weight });
      }
    }
    return y;
  };
  const textX = SIDE + COLUMNS.miles + COLUMNS.arrow;
  // The distance since the start on the right (the owner, 2026-11-10: "put the total distance on the other side"),
  // right-aligned at the row's top; the big figure on the left is the distance from the cue before.
  const total = [
    { text: `${markerFigure(row.atM)} ${metricFirst() ? "km" : "mi"}`, px: PX.total, weight: 700 as const },
    { text: "total", px: PX.unit, weight: 400 as const },
  ];
  let ty = PAD;
  for (const t of total) {
    ty += Math.round(t.px * 1.15);
    lines.push({ ...t, x: LOCK_WIDTH - SIDE - Math.ceil(measure(t.text, t.px, t.weight)), y: ty - Math.round(t.px * 0.2) });
  }
  const bottoms = [
    column(SIDE, COLUMNS.miles, [
      { text: markerFigure(row.atM - sinceM), px: PX.miles, weight: 700, whole: true },
      // The rider's units alone (the owner, 2026-11-10: "no need for km here, make it either or").
      { text: metricFirst() ? "km" : "mi", px: PX.unit, weight: 400 },
    ]),
    column(textX, LOCK_WIDTH - SIDE - COLUMNS.total - textX, [
      { text: row.turn, px: PX.turn, weight: 700 },
      ...(row.reason ? [{ text: row.reason, px: PX.reason, weight: 400 as const }] : []),
      // A named stop says its number too ("make sure stops are listed", the owner, 2026-11-10).
      ...(row.arrow.kind === "stop" && row.arrow.number != null && row.turn !== `Stop ${row.arrow.number}` ? [{ text: `Stop ${row.arrow.number}`, px: PX.reason, weight: 400 as const }] : []),
      ...(row.road ? [{ text: abbreviateStreet(row.road), px: PX.road, weight: 400 as const }] : []),
      ...(row.then ? [{ text: row.then, px: PX.then, weight: 700 as const }] : []),
    ]),
    PAD + ARROW_PX,
  ];
  return { lines, height: Math.max(...bottoms) + PAD };
}

/** Where a row's picture goes, from the row's top. */
const arrowAt = (top: number) => ({ x: SIDE + COLUMNS.miles + Math.round((COLUMNS.arrow - ARROW_PX) / 2) - 10, y: top + PAD, size: ARROW_PX });

function block(texts: string[], px: number, weight: Weight, top: number, measure: Measure): { lines: LockLine[]; bottom: number } {
  const lines: LockLine[] = [];
  let y = top;
  for (const t of texts) {
    for (const text of wrapPx(t, px, weight, LOCK_WIDTH - 2 * SIDE, measure)) {
      y += Math.round(px * 1.25);
      lines.push({ text, x: SIDE, y, px, weight });
    }
  }
  return { lines, bottom: y };
}

/** The images for the route: one, or as many as its cues need, each with its lines placed. */
export function lockScreenLayout(route: LockRoute, measure: Measure, vias: readonly number[] = [], names: ReadonlyMap<number, string> = new Map()): LockPage[] {
  const cues = cueRows(route, "strip", vias, names);
  const rows = cues.map((r, i) => rowLines(r, i ? cues[i - 1].atM : 0, measure));
  // The credits on the last image only, a source to a line (the owner, 2026-11-10: "Have credits on the final image in
  // the set, own set of lines"); the cues' images carry none.
  const credits = (full: boolean) => {
    const sources = route.attribution?.length ? ["Route data:", ...route.attribution] : [creditLine([])];
    const lines = full ? [...sources, `Planned with ${CREATOR}.`].flatMap((t) => wrapPx(t, PX.credit, 400, LOCK_WIDTH - 2 * SIDE, measure)) : [];
    return { lines, top: LOCK_HEIGHT - CLEAR_BOTTOM - 16 - lines.length * Math.round(PX.credit * 1.25) };
  };
  const bare = credits(false);
  const full = credits(true);
  // The header's height is the same on every image (the part line is there on each when there is more than one).
  const head = (part: string | null) => {
    const title = block([exportName(route)], PX.title, 700, CLEAR_TOP + 8, measure);
    const summary = block([summaryLine(route)], PX.summary, 400, title.bottom, measure);
    const marked = part ? block([part], PX.part, 700, summary.bottom, measure) : { lines: [], bottom: summary.bottom };
    return { lines: [...title.lines, ...summary.lines, ...marked.lines], bottom: marked.bottom };
  };
  // Rows by height onto images, a new image where the next row would run into the bottom band.
  const paginate = (indices: readonly number[], cueTop: number, creditTop: number) => {
    const pages: number[][] = [[]];
    let y = cueTop;
    for (const i of indices) {
      if (y + rows[i].height > creditTop - 16 && pages[pages.length - 1].length) {
        pages.push([]);
        y = cueTop;
      }
      pages[pages.length - 1].push(i);
      y += rows[i].height;
    }
    return pages;
  };
  // The owner, 2026-11-10: "Have splits at stops ... Unless it would fit in one. Otherwise have the top be the start
  // or a stop, and bottom be the next stop or end. The stop on the first page will be repeated on the next".
  const legs = (cueTop: number) => {
    const out: number[][] = [];
    let leg: number[] = [];
    rows.forEach((_, i) => {
      leg.push(i);
      if (cues[i].arrow.kind === "stop" && i > 0 && i < rows.length - 1) {
        out.push(...paginate(leg, cueTop, bare.top));
        leg = [i];
      }
    });
    if (leg.length > 1 || !out.length) out.push(...paginate(leg, cueTop, bare.top));
    return out;
  };
  // The credits on an image of their own, last, in type large enough to read (the owner, 2026-11-10: "If the credits
  // wouldn't fit on the final page with the routes, let it go on an additional one ... or just make that the
  // default, so they are readable").
  const all = rows.map((_, i) => i);
  const partTop = head("Part 88 of 88").bottom + 24;
  const cueGroups = paginate(all, partTop, bare.top).length === 1 ? [all] : legs(partTop);
  const groups = [...cueGroups, []];
  return groups.map((group, p) => {
    const part = groups.length > 1 ? `Part ${p + 1} of ${groups.length}` : null;
    const header = head(part);
    const lines: LockLine[] = [...header.lines];
    const cueTop = header.bottom + 24;
    const rules: number[] = [cueTop];
    const arrows: LockPage["arrows"] = [];
    let y = cueTop;
    for (const i of group) {
      for (const l of rows[i].lines) lines.push({ ...l, y: l.y + y });
      arrows.push({ ...arrowAt(y), arrow: cues[i].arrow });
      y += rows[i].height;
      rules.push(y);
    }
    // The credits' own image has them under its header.
    const credit = p === groups.length - 1 ? { ...full, top: cueTop } : bare;
    credit.lines.forEach((text, i) => lines.push({ text, x: SIDE, y: credit.top + (i + 1) * Math.round(PX.credit * 1.25), px: PX.credit, weight: 400 }));
    // A stop that ended the image before and heads this one is counted once.
    const repeated = p > 0 && groups[p - 1][groups[p - 1].length - 1] === group[0] ? 1 : 0;
    return { part, lines, rules, arrows, cues: group.length - repeated, cueTop, cueBottom: bare.top - 16 };
  });
}

/** Each image's file name: "routemaker-default-1_9mi-lock.png", or "...-lock-1-of-3.png" and on. */
export function lockScreenFileNames(route: Pick<RouteResponse, "preset" | "distance_m">, count: number): string[] {
  const base = exportFileName(route).replace(/\.gpx$/, "-lock");
  return count === 1 ? [`${base}.png`] : Array.from({ length: count }, (_, i) => `${base}-${i + 1}-of-${count}.png`);
}

const cuesWord = (cues: number) => `${cues} ${cues === 1 ? "cue" : "cues"}`;

/** The one image's line, for the GPX section's status region. */
export function lockScreenLine(pages: readonly Pick<LockPage, "cues">[]): string {
  return `Cue sheet image: ${cuesWord(pages.reduce((n, p) => n + p.cues, 0))} on one image, for a phone lock screen.`;
}

/** The download button's words while parts are left to save: "Download part 2 of 6". */
export function lockPartButton(next: number, count: number): string {
  return `Download part ${next + 1} of ${count}`;
}

/** Several images sent to the phone's share sheet together. */
export function lockSharedLine(count: number, cues: number): string {
  return `Cue sheet image: ${cuesWord(cues)} on ${count} images, Part 1 of ${count} to Part ${count} of ${count}, sent to the share sheet together.`;
}

/** One part saved, said only once it is: what is left and the button that saves it. */
export function lockPartLine(saved: number, count: number, cues: number): string {
  const head = `Cue sheet image: part ${saved} of ${count} saved (${cuesWord(cues)} on ${count} images).`;
  return saved < count ? `${head} Press ${lockPartButton(saved, count)} for the next.` : `${head} All ${count} are saved.`;
}

/** The share sheet closed without sending: nothing saved, and how to save them one at a time instead. */
export function lockCancelledLine(count: number): string {
  return `Cue sheet image: sharing cancelled, nothing saved. Press ${lockPartButton(0, count)} to save them one at a time.`;
}
