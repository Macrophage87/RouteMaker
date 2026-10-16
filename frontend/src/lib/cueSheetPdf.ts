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
  /** Metres from the start along the line. */
  atM: number;
  /** "Left", "Right", "Start", "Stop 1", "Caution", "Walk", "Note", "Finish". */
  turn: string;
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

function rowOf(cue: RouteCue): CueRow {
  const plainTurn = cue.type === "left" || cue.type === "right";
  return {
    type: cue.type,
    atM: cue.atM,
    turn: cue.type === "stop" ? cue.name : TURN_WORDS[cue.type],
    road: cue.street ?? "",
    // A turn's words are the turn and the street, already in the row; "Start." and "Stop 1." say no more either.
    notes: plainTurn || cue.type === "start" || cue.type === "stop" ? "" : cue.text,
  };
}

/** The rows of a sheet: every cue on the rider sheet; on the strip, all but the notes on the road's stress and surface. */
export function cueRows(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): CueRow[] {
  const rows = routeCues(route, vias).map(rowOf);
  return kind === "strip" ? rows.filter((r) => r.type !== "note") : rows;
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
 * What the download made, for the GPX section's status line: "PDF cue sheet: 8 cues, on letter paper." or "PDF
 * handlebar strip: 7 cues, 3 by 11 inches (7.6 by 27.9 cm); print at actual size and cut out."
 */
export function cueSheetLine(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): string {
  const rows = cueRows(route, kind, vias).length;
  const cues = `${rows.toLocaleString("en-US")} ${rows === 1 ? "cue" : "cues"}`;
  return kind === "sheet"
    ? `PDF cue sheet: ${cues}, on letter paper.`
    : `PDF handlebar strip: ${cues}, 3 by 11 inches (7.6 by 27.9 cm); print at actual size and cut out.`;
}

/** The document's title: "Cue sheet, Default route, 1.9 mi (3.0 km)". */
export function cueSheetTitle(route: Pick<RouteResponse, "preset" | "distance_m">, kind: CueSheetKind): string {
  return `${kind === "sheet" ? "Cue sheet" : "Handlebar cue strip"}, ${exportName(route)}`;
}

/** A column: its head, its width, and its cell's text, wrapped in the column's face and size or set as given parts. */
interface Column {
  head: string;
  width: number;
  cell: (row: CueRow) => string | { text: string; size: number; font: PdfFont }[];
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
  /** A paragraph of wrapped lines under `owner`. */
  para(owner: StructElement | null, text: string, size: number, font: PdfFont, gapAfter: number): void {
    const lead = size * 1.25;
    for (const line of spaced(wrapText(text, font, size, this.pdf.width - 2 * this.margin.side))) {
      this.need(lead);
      this.y -= lead;
      this.pdf.text(this.page, owner, this.margin.side, this.y + size * 0.25, size, font, line);
    }
    this.y -= gapAfter;
  }
}

/** The footer on each page, once the count is known: the credit and "Page 1 of 2", as Artifacts. */
function footers(pdf: TaggedPdf, side: number, y: number, size: number, credit: string): void {
  for (let page = 0; page < pdf.pageCount; page += 1) {
    const mark = `Page ${page + 1} of ${pdf.pageCount}`;
    const room = pdf.width - 2 * side - textWidth(mark, "regular", size) - 8;
    const lines = wrapText(credit, "regular", size, room);
    lines.forEach((line, i) => pdf.text(page, null, side, y + (lines.length - 1 - i) * size * 1.2, size, "regular", line));
    pdf.text(page, null, pdf.width - side - textWidth(mark, "regular", size), y, size, "regular", mark);
  }
}

/** A table of rows, its header row tagged once and carried onto later pages as an Artifact. */
function table(flow: Flow, rows: readonly CueRow[], columns: readonly Column[], size: number, headSize: number, pad: number): void {
  const { pdf, margin } = flow;
  const tableEl = pdf.element("Table");
  const headLead = headSize * 1.2;
  const right = pdf.width - margin.side;
  const header = (tagged: boolean) => {
    flow.need(headLead + pad * 2 + size * 1.2 + pad * 2);
    const tr = tagged ? pdf.element("TR", tableEl) : null;
    flow.y -= pad + headLead;
    let x = margin.side;
    for (const c of columns) {
      const th = tr ? pdf.element("TH", tr, "Column") : null;
      pdf.text(flow.page, th, x + pad, flow.y + headSize * 0.25, headSize, "bold", c.head);
      x += c.width;
    }
    flow.y -= pad;
    pdf.rule(flow.page, margin.side, flow.y, right, flow.y, 1);
  };
  header(true);
  for (const row of rows) {
    // Each cell's lines, each with its own size and the depth of its baseline below the row's top.
    const cells = columns.map((c) => {
      const made = c.cell(row);
      const parts = typeof made === "string" ? [{ text: made, size, font: c.font }] : made;
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
    const height = Math.max(...cells.map((l) => l[l.length - 1]?.depth ?? 0)) + pad;
    if (flow.need(height)) header(false);
    const tr = pdf.element("TR", tableEl);
    let x = margin.side;
    columns.forEach((c, i) => {
      const td = pdf.element("TD", tr);
      for (const part of cells[i]) {
        if (part.line) pdf.text(flow.page, td, x + pad, flow.y - part.depth + part.size * 0.25, part.size, part.font, part.line);
      }
      x += c.width;
    });
    flow.y -= height;
    pdf.rule(flow.page, margin.side, flow.y, right, flow.y, 0.4);
  }
}

const LETTER = { width: 612, height: 792 };
/** 3 by 11 inches: a strip to print at actual size and cut out. */
const STRIP = { width: 216, height: 792 };

/** The PDF file of a cue sheet for the route shown. `vias` are the plan's via points by index, not cues, as in Ride. */
export function cueSheetPdf(route: SheetRoute, kind: CueSheetKind, vias: readonly number[] = []): Uint8Array<ArrayBuffer> {
  const rows = cueRows(route, kind, vias);
  const title = cueSheetTitle(route, kind);
  const credit = sheetCredit(route);
  if (kind === "sheet") {
    const pdf = new TaggedPdf(LETTER.width, LETTER.height, { title, creator: CREATOR, lang: "en-US" });
    const flow = new Flow(pdf, { top: 54, bottom: 66, side: 54 });
    flow.para(pdf.element("H1"), exportName(route), 18, "bold", 4);
    flow.para(pdf.element("P"), `Rider cue sheet. ${summaryLine(route)}`, 11, "regular", 10);
    const warnings = sheetWarnings(route);
    if (warnings.length) {
      flow.para(pdf.element("H2"), "Warnings", 13, "bold", 2);
      for (const w of warnings) flow.para(pdf.element("P"), w, 10.5, "regular", 4);
      flow.y -= 6;
    }
    flow.para(pdf.element("H2"), "Cues", 13, "bold", 2);
    table(
      flow,
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
    flow.y -= 12;
    flow.para(pdf.element("H2"), "Credits", 13, "bold", 2);
    flow.para(pdf.element("P"), credit, 10, "regular", 0);
    footers(pdf, 54, 36, 8, credit);
    return pdf.bytes();
  }
  const pdf = new TaggedPdf(STRIP.width, STRIP.height, { title, creator: CREATOR, lang: "en-US" });
  const flow = new Flow(pdf, { top: 18, bottom: 40, side: 12 });
  flow.para(pdf.element("H1"), exportName(route), 11, "bold", 2);
  flow.para(pdf.element("P"), `Handlebar cue strip. ${summaryLine(route)}`, 7.5, "regular", 4);
  table(
    flow,
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
      { head: "Turn", width: 58, cell: (r) => r.turn, font: "bold" },
      { head: "Road", width: STRIP.width - 24 - 54 - 58, cell: (r) => abbreviateStreet(r.road), font: "regular" },
    ],
    13,
    8,
    3,
  );
  flow.y -= 6;
  flow.para(pdf.element("P"), credit, 6.5, "regular", 0);
  footers(pdf, 12, 14, 6, credit);
  return pdf.bytes();
}
