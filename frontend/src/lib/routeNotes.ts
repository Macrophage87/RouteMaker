/**
 * Route notes (Stephen 2026-11-10: "Allow for notes to be added through the mcp. Such as a dangerous intersection or
 * a point of interest", "And put a mechanism in in plan"): a spot on the map with a short line of the rider's own
 * words, a Caution or a Point of interest. Added in Plan from the map's long-press menu (Add note) or by an assistant
 * through the connector (mcp/routemaker_mcp.py `route_notes`), and kept in the route's link (`nt=`), so a saved or
 * shared route keeps its notes. A note near the line is a cue: a row of the cue sheets, the phone images and the
 * device courses, and said in Ride as the rider comes to it (his pick, 2026-11-10: "Yes, in Ride too").
 *
 * The words are the rider's own and are never translated; only "Caution" and "Note" around them are.
 */
import type { LonLat } from "./geo.ts";
import { t } from "./i18n.ts";

export type NoteKind = "caution" | "interest";

export interface RouteNote {
  at: LonLat;
  kind: NoteKind;
  text: string;
  /** Its sign on the map (Stephen 2026-11-10: "have that note appear on the map with a choice of icon"); the kind's own when absent. */
  icon?: NoteIcon;
}

/**
 * The icons a note can show on the map, our default set (Stephen asked for "a choice of icon", 2026-11-10; the set is
 * ours). Emoji, so the map, the app's dialog and the assistant's view draw the same picture with no image files.
 */
export const NOTE_ICONS = {
  warning: "⚠️",
  pothole: "🕳️",
  traffic: "🚗",
  construction: "🚧",
  view: "🏞️",
  photo: "📷",
  water: "💧",
  food: "🍴",
  coffee: "☕",
  restroom: "🚻",
  bikeshop: "🔧",
  pin: "📍",
} as const;
export type NoteIcon = keyof typeof NOTE_ICONS;
/** Each kind's icon where none was chosen. */
export const KIND_ICON: Record<NoteKind, NoteIcon> = { caution: "warning", interest: "pin" };

export function isNoteIcon(value: unknown): value is NoteIcon {
  return typeof value === "string" && Object.hasOwn(NOTE_ICONS, value);
}

/** The note's icon: its own, else its kind's. */
export function noteIcon(note: Pick<RouteNote, "kind" | "icon">): NoteIcon {
  return note.icon ?? KIND_ICON[note.kind];
}

/** A note's words at most (our default, unmeasured: a line on a phone image and a few seconds said). */
export const NOTE_TEXT_MAX = 80;
/** Notes on a route at most (our default): every one is a cue, and the link carries them all. */
export const MAX_NOTES = 20;
/**
 * A note this close to the line (metres) is a cue where the line passes nearest it; one further off stays on the map
 * only. Our default, unmeasured: a junction's far corner or a sight just off a trail, not a parallel street.
 */
export const NOTE_NEAR_M = 60;

/**
 * The notes' share of the link, in characters as the address writes them (our default): with the most points the
 * whole link stays under the server's 2048 for a saved or shared route (core/accounts.py HASH_MAX). Words in Chinese
 * or Amharic take nine characters each in the address, so fewer of them fit.
 */
export const NOTES_LINK_MAX = 1200;

/** The link's letter for each kind (`nt=c,...` and `nt=i,...`). */
const KIND_LETTER: Record<NoteKind, string> = { caution: "c", interest: "i" };

/** A note's words as kept: spaces squeezed, no control characters, at most NOTE_TEXT_MAX characters; "" for none. */
export function cleanNoteText(text: string | null | undefined): string {
  const squeezed = String(text ?? "")
    // eslint-disable-next-line no-control-regex -- control characters are what this takes out
    .replace(/[\u0000-\u001f\u007f]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return Array.from(squeezed).slice(0, NOTE_TEXT_MAX).join("").trim();
}

/**
 * The link's `nt` values: "c,-77.01234,38.89012,Busy crossing, no light", or with an icon other than the kind's own
 * "c.pothole,-77.01234,..." (the words last, so a comma in them is kept).
 */
export function encodeNotes(notes: readonly RouteNote[]): string[] {
  const out: string[] = [];
  let used = 0;
  for (const note of notes.slice(0, MAX_NOTES)) {
    const text = cleanNoteText(note.text);
    if (!text) continue;
    const icon = note.icon && note.icon !== KIND_ICON[note.kind] ? `.${note.icon}` : "";
    const value = `${KIND_LETTER[note.kind]}${icon},${note.at[0].toFixed(5)},${note.at[1].toFixed(5)},${text}`;
    // Past the link's share, the rest are left out (the page never lets it come to that: notesFit).
    used += linkLength(value);
    if (used > NOTES_LINK_MAX) break;
    out.push(value);
  }
  return out;
}

/** A `nt` value's length in the address ("&nt=" and the value as URLSearchParams writes it). */
function linkLength(value: string): number {
  return 4 + new URLSearchParams({ nt: value }).toString().length - 3;
}

/** Whether every one of `notes` fits the link (NOTES_LINK_MAX, MAX_NOTES). */
export function notesFit(notes: readonly RouteNote[]): boolean {
  return notes.length <= MAX_NOTES && encodeNotes(notes).length === notes.filter((n) => cleanNoteText(n.text)).length;
}

/** The `nt` values read back; one that does not read is left out. */
export function decodeNotes(values: readonly string[]): RouteNote[] {
  const out: RouteNote[] = [];
  for (const value of values) {
    const m = /^([ci])(?:\.([a-z]+))?,(-?\d{1,3}(?:\.\d+)?),(-?\d{1,2}(?:\.\d+)?),(.*)$/s.exec(value);
    if (!m) continue;
    const lon = Number(m[3]);
    const lat = Number(m[4]);
    const text = cleanNoteText(m[5]);
    if (!text || Math.abs(lon) > 180 || Math.abs(lat) > 90) continue;
    const kind: NoteKind = m[1] === "c" ? "caution" : "interest";
    // An icon this page does not know (a newer link's) is the kind's own.
    const icon = isNoteIcon(m[2]) && m[2] !== KIND_ICON[kind] ? { icon: m[2] } : {};
    out.push({ at: [lon, lat], kind, text, ...icon });
    if (out.length >= MAX_NOTES) break;
  }
  return out;
}

/**
 * The page's notes (App.tsx keeps them here as it renders), read where the page's link, saved route or export is
 * made, as the page's stop names are read from VIA_MARKS; a test passes its own.
 */
export const PAGE_NOTES: { list: readonly RouteNote[] } = { list: [] };

/** What Ride says and shows for a note: "Caution: busy crossing, no light." or "Note: mural on the left." */
export function noteRideText(note: Pick<RouteNote, "kind" | "text">): string {
  // The rider's own full stop is the template's; a question or an exclamation stays as written.
  const words = note.text.replace(/[.。]+$/u, "");
  const said = note.kind === "caution" ? t("Caution: {note}.", { note: words }) : t("Note: {note}.", { note: words });
  return said.replace(/([!?！？])[.。।።]$/u, "$1");
}
