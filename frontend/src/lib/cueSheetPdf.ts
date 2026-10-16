/**
 * The PDF cue sheets (PLAN.md, Formats: "rider cue sheet as HTML and PDF; handlebar-format narrow cue sheet"), made
 * in the browser from the route shown, beside the GPX, FIT and TCX exports, with the small tagged writer in pdf.ts.
 *
 * - The rider sheet: US Letter, the route's name, its distance, climb and descent, its warnings, then every cue in
 *   a table, Miles (km) from the start, Turn, Road and Notes, and the credits.
 * - The handlebar strip: a page 3 by 11 inches to print at actual size and cut out, in large type, with the
 *   distance from the start, the turn and the road only, and the busier, calmer and unpaved notes left out.
 *
 * The cues are the FIT and TCX courses' (course.ts routeCues), so the sheet says what Ride says, in Ride's words. The
 * name is the GPX export's (gpxText.ts exportName), the ride type and the distance: no place is named, so a Home is
 * never written; the plan's own points are Start, Stop N and Finish. Credits are the GPX export's words in the
 * footer of every page (PLAN.md's per-format slot: "PDF a footer") and once at the end. Nothing depends on the
 * clock, so one route gives the same bytes.
 */
import type { RouteResponse } from "./api.ts";
import { parkNoticesOf, noticeMarkerName } from "./closureMap.ts";
import { abbreviateStreet, creditLine, routeCues, type CourseCueType, type RouteCue } from "./course.ts";
import { routeWarning } from "./dialsPanel.ts";
import { formatClimb, formatDistance, formatDuration, formatMileMarker, formatMileMarkerUnits, milesFigure } from "./format.ts";
import { CREATOR } from "./gpx.ts";
import { exportFileName, exportName } from "./gpxText.ts";
import { TaggedPdf, textWidth, wrapText, type PdfFont, type StructElement } from "./pdf.ts";

export type CueSheetKind = "sheet" | "strip";

type SheetRoute = Pick<RouteResponse, "preset" | "distance_m" | "duration_s" | "climb_m" | "descent_m" | "geometry" | "attribution"> &
  Partial<RouteResponse>;

/** One row of the sheet. */
export interface CueRow {
  type: CourseCueType;
  /** Ride's hazard: an Avoid-rated junction, a work zone or a flagged crossing (a crossing is a course's note). */
  hazard: boolean;
  /** Metres from the start along the line. */
  atM: number;
  /** "Left", "Right", "Start", "Stop 1", "Caution", "Walk", "Note", "Finish". */
  turn: string;
  /** A hazard's short reason, "Avoid-rated", "Work zone" or "Crossing"; "" otherwise. */
  reason: string;
  /** The street, in full as the API names it, or "" where it has none. */
  road: string;
  /** Ride's words where the turn and road do not say it all; "" for a plain turn. */
  notes: string;
}

const TURN_WORDS: Record<CourseCueType, string> = {
  start: "Start",
  finish: "Finish",
  stop: "Stop",
  left: "Left",
  right: "Right",
  danger: "Caution",
  walk: "Walk",
  note: "Note",
};

/** A hazard's short reason, for the strip and the lock-screen image, from the description entry it came from. */
const REASONS: Record<string, string> = { avoid: "Avoid-rated", workzone: "Work zone", junction: "Crossing" };

function rowOf(cue: RouteCue): CueRow {
  const plainTurn = cue.type === "left" || cue.type === "right";
  const hazard = cue.kind === "hazard";
  return {
    type: cue.type,
    hazard,
    atM: cue.atM,
    // A flagged crossing is a note to a course (it can be dropped there) but a caution on paper, as Ride says it.
    turn: hazard ? "Caution" : cue.type === "stop" ? cue.name : TURN_WORDS[cue.type],
    reason: hazard ? (REASONS[cue.source ?? ""] ?? "") : "",
    road: cue.street ?? "",
    // A turn's words are the turn and the street, already in the row; "Start." and "Stop 1." say no more either.
    notes: plainTurn || cue.type === "start" || cue.type === "stop" ? "" : cue.text,
  };
}

/** The rows of a sheet: every cue on the rider sheet; on the strip, all but the notes on the road's stress and surface. */
export function cueRows(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): CueRow[] {
  const rows = routeCues(route, vias).map(rowOf);
  return kind === "strip" ? rows.filter((r) => r.type !== "note" || r.hazard) : rows;
}

/** "12.4 mi (20.0 km)": the distance column's words. */
export function rowDistance(row: Pick<CueRow, "atM">): string {
  return formatMileMarker(row.atM);
}

/** The sheet's summary line: distance, climb and descent, and the moving time where the route has one. */
export function summaryLine(route: Pick<RouteResponse, "distance_m" | "climb_m" | "descent_m" | "duration_s">): string {
  const time = route.duration_s > 0 ? ` Moving time about ${formatDuration(route.duration_s)}.` : "";
  return `Distance ${formatDistance(route.distance_m)}. Climb ${formatClimb(route.climb_m)}, descent ${formatClimb(route.descent_m)}.${time}`;
}

/** The route's warnings, as the route's own notices word them: an Avoid-rated junction, the traffic-tolerant ride, parks to check. */
export function sheetWarnings(route: SheetRoute): string[] {
  const out: string[] = [];
  if (route.avoid_notice) out.push(route.avoid_notice);
  const traffic = routeWarning(route.preset, route.dials);
  if (traffic) out.push(traffic);
  for (const notice of parkNoticesOf(route as RouteResponse)) out.push(`${noticeMarkerName(notice)}.`);
  return out;
}

/** The credit for the footer: the route's credits as the GPX export words them, and the application. */
export function sheetCredit(route: Pick<RouteResponse, "attribution">): string {
  return `${creditLine(route.attribution)} Planned with ${CREATOR}.`;
}

/** The file's name: the GPX export's, "routemaker-default-1_9mi-cues.pdf" or "...-strip.pdf". */
export function cueSheetFileName(route: Pick<RouteResponse, "preset" | "distance_m">, kind: CueSheetKind): string {
  return exportFileName(route).replace(/\.gpx$/, kind === "sheet" ? "-cues.pdf" : "-strip.pdf");
}

/**
 * What the download made, for the GPX section's status line: "PDF cue sheet: 8 cues, on letter paper." (or "on 2
 * pages of letter paper"), "PDF handlebar strip: 7 cues, 3 by 11 inches (7.6 by 27.9 cm); print at actual size and
 * cut out." (or "on 3 strips, each 3 by 11 inches ...; print at actual size and cut them out.").
 */
export function cueSheetLine(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = [], pages = 1): string {
  const rows = cueRows(route, kind, vias).length;
  const cues = `${rows.toLocaleString("en-US")} ${rows === 1 ? "cue" : "cues"}`;
  if (kind === "sheet") return pages > 1 ? `PDF cue sheet: ${cues}, on ${pages} pages of letter paper.` : `PDF cue sheet: ${cues}, on letter paper.`;
  return pages > 1
    ? `PDF handlebar strip: ${cues}, on ${pages} strips, each 3 by 11 inches (7.6 by 27.9 cm); print at actual size and cut them out.`
    : `PDF handlebar strip: ${cues}, 3 by 11 inches (7.6 by 27.9 cm); print at actual size and cut out.`;
}

/** The document's title: "Cue sheet, Default route, 1.9 mi (3.0 km)". */
export function cueSheetTitle(route: Pick<RouteResponse, "preset" | "distance_m">, kind: CueSheetKind): string {
  return `${kind === "sheet" ? "Cue sheet" : "Handlebar cue strip"}, ${exportName(route)}`;
}

type Part = { text: string; size: number; font: PdfFont };

/** A column: its head, its width, and its cell's text, wrapped in the column's face and size or set as given parts. */
interface Column {
  head: string;
  width: number;
  cell: (row: CueRow) => string | Part[];
  font: PdfFont;
}

/** Wrapped lines with a space kept at each break, so the text layer reads "about 10 min", not "about10 min". */
function spaced(lines: readonly string[]): string[] {
  return lines.map((line, i) => (i < lines.length - 1 && line ? `${line} ` : line));
}

/** A page flow: text set top to bottom, a new page when the next block will not fit (footers are added at the end). */
class Flow {
  page = -1;
  y = 0;
  readonly pdf: TaggedPdf;
  readonly margin: { top: number; bottom: number; side: number };
  constructor(pdf: TaggedPdf, margin: { top: number; bottom: number; side: number }) {
    this.pdf = pdf;
    this.margin = margin;
    this.newPage();
  }
  newPage(): void {
    this.page = this.pdf.addPage();
    this.y = this.pdf.height - this.margin.top;
  }
  /** Room for `height` more points on this page, or a new page. */
  need(height: number): boolean {
    if (this.y - height >= this.margin.bottom) return false;
    this.newPage();
    return true;
  }
  /**
   * A paragraph of wrapped lines under `owner`. `keep` is the height of what must follow it on the same page (a
   * heading kept with the next block): the paragraph and that much are moved to a new page together.
   */
  para(owner: StructElement | null, text: string, size: number, font: PdfFont, gapAfter: number, keep = 0): void {
    const lead = size * 1.25;
    const lines = spaced(wrapText(text, font, size, this.pdf.width - 2 * this.margin.side));
    if (keep > 0) this.need(lines.length * lead + gapAfter + keep);
    for (const line of lines) {
      this.need(lead);
      this.y -= lead;
      this.pdf.text(this.page, owner, this.margin.side, this.y + size * 0.25, size, font, line);
    }
    this.y -= gapAfter;
  }
}

/** The mark wide enough for any page count a cue sheet reaches, to keep room for it beside the credit. */
const WIDEST_MARK = "Page 888 of 888";

/** The footer's credit lines, wrapped beside the page mark. */
function footerLines(width: number, side: number, size: number, credit: string): string[] {
  return wrapText(credit, "regular", size, width - 2 * side - textWidth(WIDEST_MARK, "regular", size) - 8);
}

/** The footer's height above its baseline `y`, so the page's bottom margin is set from it and never overlaps it. */
function footerTop(width: number, side: number, y: number, size: number, credit: string): number {
  return y + footerLines(width, side, size, credit).length * size * 1.2;
}

/** The footer on each page, once the count is known: the credit and "Page 1 of 2", as Artifacts. */
function footers(pdf: TaggedPdf, side: number, y: number, size: number, credit: string): void {
  const lines = footerLines(pdf.width, side, size, credit);
  for (let page = 0; page < pdf.pageCount; page += 1) {
    const mark = `Page ${page + 1} of ${pdf.pageCount}`;
    lines.forEach((line, i) => pdf.text(page, null, side, y + (lines.length - 1 - i) * size * 1.2, size, "regular", line));
    pdf.text(page, null, pdf.width - side - textWidth(mark, "regular", size), y, size, "regular", mark);
  }
}

interface CellLine {
  line: string;
  size: number;
  font: PdfFont;
  /** The baseline's depth below the row's top. */
  depth: number;
}

/** A table measured before it is set: each row's cells as lines, its height, and the header's. */
interface TableLayout {
  columns: readonly Column[];
  rows: { cells: CellLine[][]; height: number }[];
  headHeight: number;
  headSize: number;
  pad: number;
}

function layoutTable(rows: readonly CueRow[], columns: readonly Column[], size: number, headSize: number, pad: number): TableLayout {
  const laid = rows.map((row) => {
    // Each cell's lines, each with its own size and the depth of its baseline below the row's top.
    const cells = columns.map((c) => {
      const made = c.cell(row);
      // A part's type is made smaller (to 8 pt at least) until its longest word fits, so a long street name is
      // never split mid-word ("Massachusetts", not "Massachuse" / "tts").
      const parts = (typeof made === "string" ? [{ text: made, size, font: c.font }] : made).map((part) => {
        const longest = part.text.split(/\s+/).reduce((w, word) => Math.max(w, textWidth(word, part.font, 1)), 0);
        const fit = longest > 0 ? (c.width - pad * 2) / longest : part.size;
        return { ...part, size: Math.max(Math.min(part.size, Math.floor(fit * 2) / 2), 8) };
      });
      let depth = pad;
      const lines = parts.flatMap((part) =>
        wrapText(part.text, part.font, part.size, c.width - pad * 2).map((line) => {
          depth += part.size * 1.2;
          return { line, size: part.size, font: part.font, depth };
        }),
      );
      const text = spaced(lines.map((l) => l.line));
      return lines.map((l, j) => ({ ...l, line: text[j] }));
    });
    return { cells, height: Math.max(...cells.map((l) => l[l.length - 1]?.depth ?? 0)) + pad };
  });
  return { columns, rows: laid, headHeight: headSize * 1.2 + pad * 2, headSize, pad };
}

/** The table's header and first row: what a heading before it is kept with, and the header itself too. */
function tableKeep(t: TableLayout): number {
  return t.headHeight + (t.rows[0]?.height ?? 0);
}

/** A measured table set in the flow: header in THead, rows in TBody; the header carried onto later pages as an Artifact. */
function drawTable(flow: Flow, t: TableLayout): void {
  const { pdf, margin } = flow;
  const { columns, pad, headSize } = t;
  const tableEl = pdf.element("Table");
  const right = pdf.width - margin.side;
  const header = (tagged: boolean) => {
    const tr = tagged ? pdf.element("TR", pdf.element("THead", tableEl)) : null;
    flow.y -= pad + headSize * 1.2;
    let x = margin.side;
    for (const c of columns) {
      const th = tr ? pdf.element("TH", tr, "Column") : null;
      pdf.text(flow.page, th, x + pad, flow.y + headSize * 0.25, headSize, "bold", c.head);
      x += c.width;
    }
    flow.y -= pad;
    pdf.rule(flow.page, margin.side, flow.y, right, flow.y, 1);
  };
  // The header is kept with the first row at its real height.
  flow.need(tableKeep(t));
  header(true);
  const body = pdf.element("TBody", tableEl);
  for (const row of t.rows) {
    if (flow.need(row.height)) header(false);
    const tr = pdf.element("TR", body);
    let x = margin.side;
    columns.forEach((c, i) => {
      const td = pdf.element("TD", tr);
      for (const part of row.cells[i]) {
        if (part.line) pdf.text(flow.page, td, x + pad, flow.y - part.depth + part.size * 0.25, part.size, part.font, part.line);
      }
      x += c.width;
    });
    flow.y -= row.height;
    pdf.rule(flow.page, margin.side, flow.y, right, flow.y, 0.4);
  }
}

const LETTER = { width: 612, height: 792 };
/** 3 by 11 inches: a strip to print at actual size and cut out. */
const STRIP = { width: 216, height: 792 };

/** The strip's turn cell: the turn large, and a hazard's short reason small under it ("Caution", "Avoid-rated"). */
function stripTurn(row: CueRow): Part[] {
  return [{ text: row.turn, size: 13, font: "bold" }, ...(row.reason ? [{ text: row.reason, size: 7, font: "regular" as const }] : [])];
}

/** The PDF file of a cue sheet for the route shown. `vias` are the plan's via points by index, not cues, as in Ride. */
export function cueSheetPdf(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): Uint8Array<ArrayBuffer> {
  return cueSheetDocument(route, kind, vias).bytes;
}

/** The PDF file of a cue sheet and how many pages (or strips) it runs to. */
export function cueSheetDocument(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): { bytes: Uint8Array<ArrayBuffer>; pages: number } {
  const rows = cueRows(route, kind, vias);
  const title = cueSheetTitle(route, kind);
  const credit = sheetCredit(route);
  if (kind === "sheet") {
    const foot = { side: 54, y: 36, size: 8 };
    const pdf = new TaggedPdf(LETTER.width, LETTER.height, { title, creator: CREATOR, lang: "en-US" });
    const flow = new Flow(pdf, { top: 54, bottom: footerTop(LETTER.width, foot.side, foot.y, foot.size, credit) + 12, side: 54 });
    flow.para(pdf.element("H1"), exportName(route), 18, "bold", 4);
    flow.para(pdf.element("P"), `Rider cue sheet. ${summaryLine(route)}`, 11, "regular", 10);
    const warnings = sheetWarnings(route);
    if (warnings.length) {
      flow.para(pdf.element("H2"), "Warnings", 13, "bold", 2, 10.5 * 1.25);
      for (const w of warnings) flow.para(pdf.element("P"), w, 10.5, "regular", 4);
      flow.y -= 6;
    }
    const t = layoutTable(
      rows,
      [
        { head: "Miles (km)", width: 96, cell: rowDistance, font: "bold" },
        { head: "Turn", width: 64, cell: (r) => r.turn, font: "bold" },
        { head: "Road", width: 164, cell: (r) => r.road, font: "regular" },
        { head: "Notes", width: LETTER.width - 108 - 96 - 64 - 164, cell: (r) => r.notes, font: "regular" },
      ],
      10,
      10,
      4,
    );
    flow.para(pdf.element("H2"), "Cues", 13, "bold", 2, tableKeep(t));
    drawTable(flow, t);
    flow.y -= 12;
    flow.para(pdf.element("H2"), "Credits", 13, "bold", 2, 10 * 1.25);
    flow.para(pdf.element("P"), credit, 10, "regular", 0);
    footers(pdf, foot.side, foot.y, foot.size, credit);
    return { bytes: pdf.bytes(), pages: pdf.pageCount };
  }
  const foot = { side: 12, y: 14, size: 6 };
  const pdf = new TaggedPdf(STRIP.width, STRIP.height, { title, creator: CREATOR, lang: "en-US" });
  const flow = new Flow(pdf, { top: 18, bottom: footerTop(STRIP.width, foot.side, foot.y, foot.size, credit) + 8, side: 12 });
  flow.para(pdf.element("H1"), exportName(route), 11, "bold", 2);
  flow.para(pdf.element("P"), `Handlebar cue strip. ${summaryLine(route)}`, 7.5, "regular", 4);
  const t = layoutTable(
    rows,
    [
      {
        head: "Miles (km)",
        width: 54,
        cell: (r) => [
          { text: milesFigure(r.atM), size: 16, font: "bold" },
          { text: formatMileMarkerUnits(r.atM), size: 7, font: "regular" },
        ],
        font: "bold",
      },
      { head: "Turn", width: 50, cell: stripTurn, font: "bold" },
      { head: "Road", width: STRIP.width - 24 - 54 - 50, cell: (r) => abbreviateStreet(r.road), font: "regular" },
    ],
    13,
    8,
    3,
  );
  drawTable(flow, t);
  flow.y -= 6;
  flow.para(pdf.element("P"), credit, 6.5, "regular", 0);
  footers(pdf, foot.side, foot.y, foot.size, credit);
  return { bytes: pdf.bytes(), pages: pdf.pageCount };
}
