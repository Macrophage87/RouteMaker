/**
 * Plan's words for route notes (lib/routeNotes.ts): the note dialog (NoteDialog.tsx), Add note in the map's long-press
 * menu, a note's sign as a button and what is said as notes change. Plan only, so English and Spanish (Ride's words
 * for a note are in lib/routeNotes.ts, in every language).
 */
import { t } from "./i18n.ts";
import { MAX_NOTES, type NoteIcon, type NoteKind, type RouteNote } from "./routeNotes.ts";

/** The kind's name, as the dialog, the map and the exports say it. */
export const NOTE_KIND_WORDS: Record<NoteKind, string> = { caution: t("Caution"), interest: t("Point of interest") };

/** Each icon's name, for the dialog's choice and a screen reader (lib/routeNotes.ts NOTE_ICONS). */
export const NOTE_ICON_WORDS: Record<NoteIcon, string> = {
  warning: t("Warning"),
  pothole: t("Pothole"),
  traffic: t("Traffic"),
  construction: t("Construction"),
  view: t("View"),
  photo: t("Photo spot"),
  water: t("Water"),
  food: t("Food"),
  coffee: t("Coffee"),
  restroom: t("Restroom"),
  bikeshop: t("Bike shop"),
  pin: t("Pin"),
};
export const NOTE_ICON_LABEL = t("Icon on the map");

/** A map pin's name for screen readers: "Caution: busy crossing, no light. Press to change or remove." */
export function notePinLabel(note: Pick<RouteNote, "kind" | "text">): string {
  return `${NOTE_KIND_WORDS[note.kind]}: ${note.text}. ${t("Press to change or remove.")}`;
}

/** The note dialog's words (NoteDialog.tsx). Plan only: English and Spanish. */
export const NOTE_ADD = t("Add note");
export const NOTE_HEADING_ADD = t("Add a note");
export const NOTE_HEADING_EDIT = t("Change note");
export const NOTE_KIND_LABEL = t("Kind");
export const NOTE_TEXT_LABEL = t("Note");
export const NOTE_SAVE = t("Save note");
export const NOTE_REMOVE = t("Remove note");
export const NOTE_CANCEL = "Cancel";
export const NOTE_HINT = t("Shown on the map, the cue sheets and phone images, and said in Ride as you reach it.");

/** Said as a note is added, changed or removed. */
export function noteSaid(change: "added" | "changed" | "removed"): string {
  return change === "added" ? t("Note added.") : change === "changed" ? t("Note changed.") : t("Note removed.");
}

/** Said when a note's words would not fit the route's link (routeNotes.ts NOTES_LINK_MAX). */
export function noteTooLongSaid(): string {
  return t("The route's notes are too long for its link: shorten this note or another.");
}

/** Said when the route already has MAX_NOTES notes. */
export function notesFullSaid(): string {
  return t("The route has the most notes it can ({max}).", { max: MAX_NOTES });
}
