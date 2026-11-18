/**
 * Plan's keyboard shortcuts (the 2026-11-12 backlog, Plan experience item 11; Stephen picked it for v0.28.0):
 * "/" to the search box, R reverse, L loop, Enter to route, S save, E export, Delete removes the selected point,
 * [ and ] step through the points, 1 to 5 open a route fold, and ? the sheet that lists them.
 *
 * Single keys can be set off by speech input or a stray press, so the sheet has an off switch (WCAG 2.1.4,
 * Character Key Shortcuts), kept on this device. Enter, Delete, Ctrl+Z and Ctrl+Enter are not
 * character keys and stay on.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import { typesText } from "./editHistory.ts";
import { t } from "./i18n.ts";

export type PlanKey =
  | { kind: "search" | "reverse" | "loop" | "route" | "save" | "export" | "remove" | "previous" | "next" | "help" }
  | { kind: "fold"; index: number };

/** The keys as the sheet lists them, in its order. */
export const PLAN_KEY_ROWS: ReadonlyArray<{ keys: readonly string[]; what: string }> = [
  { keys: ["/"], what: t("Go to the search box") },
  { keys: ["Enter"], what: t("Route (with the focus on the map or the page)") },
  { keys: ["R"], what: t("Reverse the points") },
  { keys: ["L"], what: t("Next way to end: one way, loop, out and back") },
  { keys: ["[", "]"], what: t("Previous or next point") },
  { keys: ["Delete"], what: t("Remove the selected point") },
  { keys: ["S"], what: t("Save the route") },
  { keys: ["E"], what: t("Download the route as GPX") },
  { keys: ["1", "–", "5"], what: t("Open a fold of the route summary") },
  { keys: ["?"], what: t("This list") },
];

export const PLAN_KEYS_TITLE = t("Keyboard shortcuts");
export const PLAN_KEYS_SWITCH = t("Use single-key shortcuts");
export const PLAN_KEYS_SWITCH_HINT = t("Turn off if speech input or stray presses set them off. Enter, Delete, Ctrl+Z and Ctrl+Enter still work.");

/** What a shortcut says when it can do nothing now (the page's status line). */
export const planKeySaid = {
  noSearch: () => t("Open the planner to search."),
  twoPoints: () => t("Add two points first."),
  noLoop: () => t("This ride type has no loop."),
  chooseFirst: () => t("Choose a route first, then save it."),
  routeToSave: () => t("Route first, then save."),
  routeToExport: () => t("Route first, then download it."),
  noPoints: () => t("No points yet."),
  pickPoint: () => t("Pick a point first with [ or ]."),
  noFolds: () => t("Route first: the folds are in the route summary."),
  folds: (count: number) => t("The route summary has {count} folds.", { count }),
};

const STORE_KEY = "routemaker.planKeys";

/** On unless the rider turned them off on this device. */
export function readPlanKeys(store: KeyValueStore | null = browserStore()): boolean {
  try {
    return store?.getItem(STORE_KEY) !== "off";
  } catch {
    return true;
  }
}

export function writePlanKeys(on: boolean, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(STORE_KEY, on ? "on" : "off");
  } catch {
    // Kept for this visit only.
  }
}

interface KeyLike {
  key: string;
  ctrlKey: boolean;
  metaKey: boolean;
  altKey: boolean;
  shiftKey: boolean;
}

/** Enter and Delete are not character keys (WCAG 2.1.4): the off switch leaves them on. */
export function characterKey(key: PlanKey): boolean {
  return key.kind !== "route" && key.kind !== "remove";
}

/** What a key press asks of Plan, or null when it is not one of the shortcuts. */
export function planKeyFor(event: KeyLike): PlanKey | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  // "?" is Shift+/ on most layouts: the key, not the Shift, decides.
  if (event.key === "?") return { kind: "help" };
  if (event.shiftKey) return null;
  switch (event.key) {
    case "/":
      return { kind: "search" };
    case "Enter":
      return { kind: "route" };
    case "Delete":
    case "Backspace":
      return { kind: "remove" };
    case "[":
      return { kind: "previous" };
    case "]":
      return { kind: "next" };
  }
  switch (event.key.toLowerCase()) {
    case "r":
      return { kind: "reverse" };
    case "l":
      return { kind: "loop" };
    case "s":
      return { kind: "save" };
    case "e":
      return { kind: "export" };
  }
  if (/^[1-5]$/.test(event.key)) return { kind: "fold", index: Number(event.key) - 1 };
  return null;
}

/** Controls whose own keys a shortcut must not take: a letter types ahead in a list, Enter presses a button. */
const OWN_KEYS = "button, a[href], select, summary, [role=button], [role=link], [role=option], [role=listbox], [role=combobox], [role=menuitem], [role=radio], [role=checkbox], [role=tab], [role=slider], input";

/**
 * Whether a shortcut may act with the focus on `target`: never in a text box; Enter and Delete only away from
 * controls (Enter presses a button, Delete may mean something in a list), the others anywhere but a list or a select.
 */
export function keyFreeAt(key: PlanKey, target: Element | null): boolean {
  if (!target || typeof target.closest !== "function") return true;
  if (typesText(target as HTMLElement)) return false;
  if (target.closest("select, [role=listbox], [role=combobox], [role=slider]")) return false;
  if (key.kind === "route") return !target.closest(OWN_KEYS);
  // Delete on a point's own row is meant for that point (its Remove or grip has the focus).
  if (key.kind === "remove") return !target.closest(OWN_KEYS) || !!target.closest(".points li");
  return true;
}

/** The next point to step to with [ or ] from `from` (null: none chosen yet), among `count` points. */
export function stepPoint(from: number | null, count: number, direction: -1 | 1): number | null {
  if (count <= 0) return null;
  if (from === null || from < 0 || from >= count) return direction === 1 ? 0 : count - 1;
  return Math.min(count - 1, Math.max(0, from + direction));
}
