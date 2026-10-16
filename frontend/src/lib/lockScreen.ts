/**
 * The cue sheet as a phone lock-screen image (the owner, 2026-10-16: "a lot of people take pictures of them on their
 * phones and use them as lock screens"): a portrait PNG drawn in the browser (app/lockScreenRender.ts), 1179 by 2556
 * pixels (an iPhone Pro's screen; an Android phone fits it to its own), in large type like the handlebar strip.
 *
 * This module is the layout alone, pure, so it is tested without a canvas: every line of text with its place, size
 * and weight, given a `measure` for text widths. The top 28% is left clear for the lock screen's clock and the
 * bottom 12% for its controls; the route's name and distance sit small just under the top band and the credits
 * small just above the bottom one. The rows are the strip's (cueSheetPdf.ts cueRows "strip"): the miles from the
 * start large with km small, the turn with a caution's reason small, and the road abbreviated. Rows that do not fit
 * on one image go on the next, "Part 2 of 3". Dark text on white. No place is named (exportName), so never a Home.
 */
import type { RouteResponse } from "./api.ts";
import { abbreviateStreet } from "./course.ts";
import { cueRows, sheetCredit, summaryLine, type CueRow } from "./cueSheetPdf.ts";
import { formatMileMarkerUnits, milesFigure } from "./format.ts";
import { exportFileName, exportName } from "./gpxText.ts";

export const LOCK_WIDTH = 1179;
export const LOCK_HEIGHT = 2556;
/** The lock screen's own clock and widgets above, its controls below: no cue is drawn in either band. */
export const CLEAR_TOP = Math.round(LOCK_HEIGHT * 0.28);
export const CLEAR_BOTTOM = Math.round(LOCK_HEIGHT * 0.12);
export const INK = "#111111";
export const PAPER = "#ffffff";

const SIDE = 64;
const PAD = 14;
const COLUMNS = { miles: 280, turn: 330 } as const;
const PX = { title: 40, summary: 30, part: 30, miles: 96, unit: 32, turn: 64, reason: 32, road: 60, credit: 26 } as const;

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
function rowLines(row: CueRow, measure: Measure): { lines: LockLine[]; height: number } {
  const lines: LockLine[] = [];
  const column = (x: number, width: number, parts: { text: string; px: number; weight: Weight }[]) => {
    let y = PAD;
    for (const part of parts) {
      for (const text of wrapPx(part.text, part.px, part.weight, width - PAD, measure)) {
        y += Math.round(part.px * 1.15);
        lines.push({ text, x, y: y - Math.round(part.px * 0.2), px: part.px, weight: part.weight });
      }
    }
    return y;
  };
  const turnX = SIDE + COLUMNS.miles;
  const roadX = turnX + COLUMNS.turn;
  const bottoms = [
    column(SIDE, COLUMNS.miles, [
      { text: milesFigure(row.atM), px: PX.miles, weight: 700 },
      { text: formatMileMarkerUnits(row.atM), px: PX.unit, weight: 400 },
    ]),
    column(turnX, COLUMNS.turn, [
      { text: row.turn, px: PX.turn, weight: 700 },
      ...(row.reason ? [{ text: row.reason, px: PX.reason, weight: 400 as const }] : []),
    ]),
    column(roadX, LOCK_WIDTH - SIDE - roadX, row.road ? [{ text: abbreviateStreet(row.road), px: PX.road, weight: 400 }] : []),
  ];
  return { lines, height: Math.max(...bottoms) + PAD };
}

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
export function lockScreenLayout(route: LockRoute, measure: Measure, vias: readonly number[] = []): LockPage[] {
  const rows = cueRows(route, "strip", vias).map((r) => rowLines(r, measure));
  const credit = wrapPx(sheetCredit(route), PX.credit, 400, LOCK_WIDTH - 2 * SIDE, measure);
  const creditTop = LOCK_HEIGHT - CLEAR_BOTTOM - 16 - credit.length * Math.round(PX.credit * 1.25);
  // The header's height is the same on every image (the part line is there on each when there is more than one).
  const head = (part: string | null) => {
    const title = block([exportName(route)], PX.title, 700, CLEAR_TOP + 8, measure);
    const summary = block([summaryLine(route)], PX.summary, 400, title.bottom, measure);
    const marked = part ? block([part], PX.part, 700, summary.bottom, measure) : { lines: [], bottom: summary.bottom };
    return { lines: [...title.lines, ...summary.lines, ...marked.lines], bottom: marked.bottom };
  };
  const fill = (cueTop: number) => {
    const pages: number[][] = [[]];
    let y = cueTop;
    rows.forEach((r, i) => {
      if (y + r.height > creditTop - 16 && pages[pages.length - 1].length) {
        pages.push([]);
        y = cueTop;
      }
      pages[pages.length - 1].push(i);
      y += r.height;
    });
    return pages;
  };
  let groups = fill(head(null).bottom + 24);
  if (groups.length > 1) groups = fill(head("Part 88 of 88").bottom + 24);
  return groups.map((group, p) => {
    const part = groups.length > 1 ? `Part ${p + 1} of ${groups.length}` : null;
    const header = head(part);
    const lines: LockLine[] = [...header.lines];
    const cueTop = header.bottom + 24;
    const rules: number[] = [cueTop];
    let y = cueTop;
    for (const i of group) {
      for (const l of rows[i].lines) lines.push({ ...l, y: l.y + y });
      y += rows[i].height;
      rules.push(y);
    }
    credit.forEach((text, i) => lines.push({ text, x: SIDE, y: creditTop + (i + 1) * Math.round(PX.credit * 1.25), px: PX.credit, weight: 400 }));
    return { part, lines, rules, cues: group.length, cueTop, cueBottom: creditTop - 16 };
  });
}

/** Each image's file name: "routemaker-default-1_9mi-lock.png", or "...-lock-1-of-3.png" and on. */
export function lockScreenFileNames(route: Pick<RouteResponse, "preset" | "distance_m">, count: number): string[] {
  const base = exportFileName(route).replace(/\.gpx$/, "-lock");
  return count === 1 ? [`${base}.png`] : Array.from({ length: count }, (_, i) => `${base}-${i + 1}-of-${count}.png`);
}

/** What the download made, for the GPX section's status line. */
export function lockScreenLine(pages: readonly Pick<LockPage, "cues">[]): string {
  const cues = pages.reduce((n, p) => n + p.cues, 0);
  const noun = cues === 1 ? "cue" : "cues";
  if (pages.length === 1) return `Cue sheet image: ${cues} ${noun} on one image, for a phone lock screen.`;
  return (
    `Cue sheet image: ${cues} ${noun} do not fit on one image, so there are ${pages.length}, ` +
    `Part 1 of ${pages.length} to Part ${pages.length} of ${pages.length}, downloaded one after another.`
  );
}
