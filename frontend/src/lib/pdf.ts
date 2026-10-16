/**
 * A small tagged PDF writer, for the cue sheets (cueSheetPdf.ts), with no library: text in the two standard
 * Helvetica faces, thin rules, and a structure tree so a screen reader reads the sheet in order (PLAN.md,
 * Accessibility: "The exported PDFs are tagged with a reading order, because a cue sheet is the artifact a rider
 * is most likely to need read aloud").
 *
 * PDF 1.7 (ISO 32000-1). The standard fonts are not embedded and are written in WinAnsiEncoding, so the text layer
 * is plain and extractable; a character WinAnsi has no code for is written as "?". Every text run is a marked
 * content sequence with its own MCID under a structure element (Document, H1, H2, P, Table, TR, TH, TD); what
 * repeats on each page (the footer, a table's header carried over, rules) is an Artifact, read once or not at all.
 * The catalog carries /Lang, /MarkInfo and DisplayDocTitle; each page /Tabs /S.
 *
 * Clean and reproducible (PLAN.md, Clean exports: "a cue sheet PDF omits document author and producer fields";
 * "fixed creation and modification dates, a content-derived document id"): the Info dictionary has the title and
 * the creator only, no dates at all, and the /ID is a hash of the file's own body, so one sheet always gives the
 * same bytes. The file is ASCII after its header's binary marker, and its content streams are not compressed.
 *
 * Font metrics: Adobe's Core 14 AFM widths for Helvetica and Helvetica-Bold (docs/SOURCES.md), WinAnsi codes 32-255.
 */

export type PdfFont = "regular" | "bold";

const HELVETICA = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
  556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
  556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584, 350,
  556, 350, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350, 350, 222, 222, 333, 333, 350, 556,
  1000, 333, 1000, 500, 333, 944, 350, 500, 667, 278, 333, 556, 556, 556, 556, 260, 556, 333, 737, 370, 556, 584, 333, 737,
  333, 400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365, 556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000,
  722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667,
  611, 556, 556, 556, 556, 556, 556, 889, 500, 556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556,
  584, 611, 556, 556, 556, 556, 500, 556, 500,
];
const HELVETICA_BOLD = [
  278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
  556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778,
  667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611,
  611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 350,
  556, 350, 278, 556, 500, 1000, 556, 556, 333, 1000, 667, 333, 1000, 350, 611, 350, 350, 278, 278, 500, 500, 350, 556,
  1000, 333, 1000, 556, 333, 944, 350, 500, 667, 278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737,
  333, 400, 584, 333, 333, 333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000,
  722, 667, 667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667,
  611, 556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611, 611, 611, 611, 611,
  584, 611, 611, 611, 611, 611, 556, 611, 556,
];

/** WinAnsi's codes 0x80-0x9F (Windows-1252), by Unicode code point. */
const WIN_ANSI_HIGH: Record<number, number> = {
  0x20ac: 0x80, 0x201a: 0x82, 0x0192: 0x83, 0x201e: 0x84, 0x2026: 0x85, 0x2020: 0x86, 0x2021: 0x87, 0x02c6: 0x88,
  0x2030: 0x89, 0x0160: 0x8a, 0x2039: 0x8b, 0x0152: 0x8c, 0x017d: 0x8e, 0x2018: 0x91, 0x2019: 0x92, 0x201c: 0x93,
  0x201d: 0x94, 0x2022: 0x95, 0x2013: 0x96, 0x2014: 0x97, 0x02dc: 0x98, 0x2122: 0x99, 0x0161: 0x9a, 0x203a: 0x9b,
  0x0153: 0x9c, 0x017e: 0x9e, 0x0178: 0x9f,
};

/** The text's WinAnsi codes, one per character: "?" for one WinAnsi lacks, a space for any other space or control. */
export function winAnsi(text: string): number[] {
  const out: number[] = [];
  for (const ch of text.normalize("NFC")) {
    const cp = ch.codePointAt(0) as number;
    if (cp >= 0x20 && cp <= 0x7e) out.push(cp);
    else if (cp >= 0xa0 && cp <= 0xff) out.push(cp === 0xa0 ? 0x20 : cp);
    else if (WIN_ANSI_HIGH[cp]) out.push(WIN_ANSI_HIGH[cp]);
    else if (cp < 0x20 || /\s/u.test(ch)) out.push(0x20);
    else out.push(0x3f);
  }
  return out;
}

/** The width of `text` in points at `size`. */
export function textWidth(text: string, font: PdfFont, size: number): number {
  const widths = font === "bold" ? HELVETICA_BOLD : HELVETICA;
  return (winAnsi(text).reduce((sum, code) => sum + (widths[code - 32] ?? 556), 0) * size) / 1000;
}

/** `text` broken into lines no wider than `width` at `size`, at spaces, a word too long for a line cut by characters. */
export function wrapText(text: string, font: PdfFont, size: number, width: number): string[] {
  const lines: string[] = [];
  let line = "";
  for (const word of text.trim().split(/\s+/).filter(Boolean)) {
    const tried = line ? `${line} ${word}` : word;
    if (textWidth(tried, font, size) <= width) {
      line = tried;
      continue;
    }
    if (line) lines.push(line);
    line = "";
    let rest = word;
    while (textWidth(rest, font, size) > width) {
      const chars = Array.from(rest);
      let n = chars.length - 1;
      while (n > 1 && textWidth(chars.slice(0, n).join(""), font, size) > width) n -= 1;
      lines.push(chars.slice(0, n).join(""));
      rest = chars.slice(n).join("");
    }
    line = rest;
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

export type StructType = "Document" | "H1" | "H2" | "P" | "Table" | "TR" | "TH" | "TD";

/** A structure element: its kind, and its children in reading order (elements, or marked content on a page). */
export interface StructElement {
  type: StructType;
  children: (StructElement | { page: number; mcid: number })[];
  /** A TH's scope. */
  scope?: "Column" | "Row";
}

interface Page {
  ops: string[];
  /** The element each MCID on the page belongs to, by MCID. */
  owners: StructElement[];
}

const num = (n: number) => {
  const r = Math.round(n * 100) / 100;
  return Object.is(r, -0) ? "0" : String(r);
};

/** A PDF literal string of WinAnsi codes, ASCII only: the specials escaped, anything outside printable ASCII in octal. */
function literal(codes: readonly number[]): string {
  let out = "(";
  for (const c of codes) {
    if (c === 0x28 || c === 0x29 || c === 0x5c) out += `\\${String.fromCharCode(c)}`;
    else if (c >= 0x20 && c <= 0x7e) out += String.fromCharCode(c);
    else out += `\\${c.toString(8).padStart(3, "0")}`;
  }
  return `${out})`;
}

/** A text string for the Info dictionary: UTF-16BE with its byte-order mark, as hex. */
function textString(text: string): string {
  let hex = "FEFF";
  for (let i = 0; i < text.length; i += 1) hex += text.charCodeAt(i).toString(16).toUpperCase().padStart(4, "0");
  return `<${hex}>`;
}

/** FNV-1a over the body, four ways seeded, as 32 hex digits: a document id that depends on the content alone. */
function contentId(body: string): string {
  let out = "";
  for (const seed of [0x811c9dc5, 0x01000193, 0x9e3779b9, 0x85ebca6b]) {
    let h = seed >>> 0;
    for (let i = 0; i < body.length; i += 1) {
      h ^= body.charCodeAt(i);
      h = Math.imul(h, 0x01000193) >>> 0;
    }
    out += h.toString(16).toUpperCase().padStart(8, "0");
  }
  return out;
}

export interface PdfMeta {
  title: string;
  /** The application, never a person or a device. */
  creator: string;
  /** BCP 47, "en-US". */
  lang: string;
}

export class TaggedPdf {
  readonly width: number;
  readonly height: number;
  readonly root: StructElement = { type: "Document", children: [] };
  private readonly pages: Page[] = [];
  private readonly meta: PdfMeta;

  constructor(width: number, height: number, meta: PdfMeta) {
    this.width = width;
    this.height = height;
    this.meta = meta;
  }

  get pageCount(): number {
    return this.pages.length;
  }

  /** A new page; returns its index. */
  addPage(): number {
    this.pages.push({ ops: [], owners: [] });
    return this.pages.length - 1;
  }

  /** A structure element under `parent` (the Document by default). */
  element(type: StructType, parent: StructElement = this.root, scope?: StructElement["scope"]): StructElement {
    const made: StructElement = { type, children: [], ...(scope ? { scope } : {}) };
    parent.children.push(made);
    return made;
  }

  /**
   * Text at (x, y) from the page's bottom left, its baseline at y: part of `owner` in reading order, or an Artifact
   * (read once or not at all) where `owner` is null.
   */
  text(page: number, owner: StructElement | null, x: number, y: number, size: number, font: PdfFont, text: string): void {
    const p = this.pages[page];
    const run = `BT /${font === "bold" ? "F2" : "F1"} ${num(size)} Tf ${num(x)} ${num(y)} Td ${literal(winAnsi(text))} Tj ET`;
    if (!owner) {
      p.ops.push(`/Artifact BMC ${run} EMC`);
      return;
    }
    const mcid = p.owners.length;
    p.owners.push(owner);
    owner.children.push({ page, mcid });
    p.ops.push(`/${owner.type} <</MCID ${mcid}>> BDC ${run} EMC`);
  }

  /** A thin rule, always an Artifact. */
  rule(page: number, x1: number, y1: number, x2: number, y2: number, width = 0.5): void {
    // Line width, move to, line to, stroke.
    const path = [num(width), "w", num(x1), num(y1), "m", num(x2), num(y2), "l", "S"].join(" ");
    this.pages[page].ops.push(`/Artifact BMC ${path} EMC`);
  }

  /** The file. */
  bytes(): Uint8Array<ArrayBuffer> {
    const text = this.serialize();
    const out = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i += 1) out[i] = text.charCodeAt(i) & 0xff;
    return out;
  }

  /** The file as a string of byte values (all ASCII but the header's binary marker). */
  serialize(): string {
    // Object numbers: 1 catalog, 2 pages, 3 and 4 the fonts, 5 the structure tree root, 6 its parent tree, 7 info,
    // then each page and its content stream, then the structure elements in document order.
    const objects: string[] = [];
    const pageObj = (i: number) => 8 + i * 2;
    const elements: StructElement[] = [];
    const walk = (e: StructElement) => {
      elements.push(e);
      for (const c of e.children) if ("type" in c) walk(c);
    };
    walk(this.root);
    const firstElement = 8 + this.pages.length * 2;
    const elementObj = new Map(elements.map((e, i) => [e, firstElement + i]));
    const parentOf = new Map<StructElement, StructElement>();
    for (const e of elements) for (const c of e.children) if ("type" in c) parentOf.set(c, e);

    const set = (n: number, body: string) => {
      objects[n] = body;
    };
    set(
      1,
      `<< /Type /Catalog /Pages 2 0 R /StructTreeRoot 5 0 R /MarkInfo << /Marked true >> /Lang (${this.meta.lang}) ` +
        `/ViewerPreferences << /DisplayDocTitle true >> >>`,
    );
    set(2, `<< /Type /Pages /Kids [${this.pages.map((_, i) => `${pageObj(i)} 0 R`).join(" ")}] /Count ${this.pages.length} >>`);
    set(3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
    set(4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");
    set(5, `<< /Type /StructTreeRoot /K ${elementObj.get(this.root)} 0 R /ParentTree 6 0 R /ParentTreeNextKey ${this.pages.length} >>`);
    set(
      6,
      `<< /Nums [${this.pages.map((p, i) => `${i} [${p.owners.map((o) => `${elementObj.get(o)} 0 R`).join(" ")}]`).join(" ")}] >>`,
    );
    set(7, `<< /Title ${textString(this.meta.title)} /Creator ${textString(this.meta.creator)} >>`);
    this.pages.forEach((p, i) => {
      const stream = p.ops.join("\n");
      set(
        pageObj(i),
        `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(this.width)} ${num(this.height)}] ` +
          `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${pageObj(i) + 1} 0 R /StructParents ${i} /Tabs /S >>`,
      );
      set(pageObj(i) + 1, `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
    });
    for (const e of elements) {
      const kids = e.children.map((c) => ("type" in c ? `${elementObj.get(c)} 0 R` : `<< /Type /MCR /Pg ${pageObj(c.page)} 0 R /MCID ${c.mcid} >>`));
      const parent = parentOf.get(e);
      const firstPage = e.children.find((c) => !("type" in c)) as { page: number } | undefined;
      set(
        elementObj.get(e) as number,
        `<< /Type /StructElem /S /${e.type} /P ${parent ? `${elementObj.get(parent)} 0 R` : "5 0 R"}` +
          (firstPage ? ` /Pg ${pageObj(firstPage.page)} 0 R` : "") +
          (e.scope ? ` /A << /O /Table /Scope /${e.scope} >>` : "") +
          ` /K [${kids.join(" ")}] >>`,
      );
    }

    let body = "%PDF-1.7\n%\xe2\xe3\xcf\xd3\n";
    const offsets: number[] = [];
    for (let n = 1; n < objects.length; n += 1) {
      offsets[n] = body.length;
      body += `${n} 0 obj\n${objects[n]}\nendobj\n`;
    }
    const xrefAt = body.length;
    const id = contentId(body);
    let xref = `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
    for (let n = 1; n < objects.length; n += 1) xref += `${String(offsets[n]).padStart(10, "0")} 00000 n \n`;
    return `${body}${xref}trailer\n<< /Size ${objects.length} /Root 1 0 R /Info 7 0 R /ID [<${id}> <${id}>] >>\nstartxref\n${xrefAt}\n%%EOF\n`;
  }
}
