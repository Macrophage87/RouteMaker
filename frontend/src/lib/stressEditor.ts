/**
 * The road panel's "Change LTS" (OWNER-DECISIONS 441g, 441h, 441m, 460; core/stress_edits.py): the
 * pure half. An instance admin's change of a road's traffic stress applies at once; this file holds
 * what the editor asks the API, the words it says, and what it checks before it asks.
 * StressEditor.tsx draws it.
 *
 * Phase 1 is whole steps, 1 to 5 (5 is Avoid). The words are the API's (`steps` in the editor's
 * starting state, core/segment_info.TIER_WORDS), so the panel, the editor and the map's legend
 * cannot disagree. Nothing here carries a name or an id of a person: the page learns three yes/no
 * flags (`/api/me`), a CSRF token it reads from its own cookie, and an OSM way id.
 *
 * Screen-reader first: every state change is a sentence (`savedSaid`, `undoneSaid`), the slider's
 * value is read as its words (`stepValueText`), an error names its field so the form can move the
 * focus to it, and none of it needs a pointer.
 */

/** GET /api/me: three yes/no flags, no name and no id. */
export interface Me {
  signed_in: boolean;
  can_change_lts: boolean;
  can_suggest: boolean;
}

export const NO_ME: Me = { signed_in: false, can_change_lts: false, can_suggest: false };

export interface EditorStep {
  value: number;
  words: string;
}

export type CurrentSource = "classifier" | "file" | "admin" | "panel";

export interface EditorCurrent {
  step: number;
  words: string;
  source: CurrentSource;
  at_least: boolean;
  category: string | null;
  public_note: string | null;
  display: string | null;
  private_reason: string | null;
  when: string | null;
  by: "you" | "another admin" | null;
}

export interface RecentEdit {
  id: number;
  action: string;
  at: string;
  can_undo: boolean;
}

/** GET /api/stress-edits/way/{id}: what the editor opens with. */
export interface EditorState {
  osm_way_id: number;
  classifier_step: number | null;
  can_raise_only: boolean;
  current: EditorCurrent;
  expected: string;
  steps: EditorStep[];
  categories: { id: string; label: string }[];
  reason_max: number;
  note_max: number;
  recent_edit: RecentEdit | null;
  pieces: number;
}

export interface EditedWay {
  osm_way_id: number;
  step: number;
  changed: boolean;
}

/** POST /api/stress-edits and .../undo. */
export interface EditResult {
  edit_id: number;
  ways: EditedWay[];
  generation: number;
  undo_until: string;
}

export type DisplayWhere = "route_only" | "map";

export interface SaveRequest {
  osm_way_ids: number[];
  step: number;
  at_least: boolean;
  category: string;
  reason: string;
  public_note?: string;
  display: DisplayWhere;
  expected: string;
}

export interface Refusal {
  kind: "refused";
  status: number;
  message: string;
  /** The form field the problem is about, so the focus can go there. */
  field: string | null;
  code: string | null;
}

export type EditorLoad =
  | { kind: "loading" }
  | { kind: "ready"; state: EditorState }
  | { kind: "error"; message: string };

export type SaveOutcome = { kind: "saved"; result: EditResult } | Refusal;

/** The words on the button and the editor's heading (OWNER-DECISIONS 441m). */
export const CHANGE_LTS_TEXT = "Change LTS";
export const EDITOR_HEADING = "Change traffic stress";
export const LEVEL_LABEL = "Traffic stress level";
export const RAISE_ONLY_LABEL = "Only raise it";
export const RAISE_ONLY_HELP = "Keep the current level if it is already higher.";
export const RAISE_ONLY_UNAVAILABLE =
  "Not available here: an earlier override hides the level the classifier gave this road. Set an exact level instead.";
export const CATEGORY_LABEL = "Reason category";
export const REASON_LABEL = "Private reason (never shown to riders)";
export const NOTE_LABEL = "Public note (optional)";
export const NOTE_HELP = "Describe the road and its traffic. Never a neighbourhood or its people.";
export const DISPLAY_LABEL = "Show the note";
export const DISPLAY_OPTIONS: ReadonlyArray<{ value: DisplayWhere; text: string }> = [
  { value: "route_only", text: "On routes over this road only" },
  { value: "map", text: "Also when someone clicks the road on the map" },
];
export const UNDO_MINUTES = 30;
export const AFTER_REBUILD =
  "The map shows it now; routes fully use it after the next weekly data update.";

/** The slider's value as it is read out: "3, For experienced cyclists". */
export function stepValueText(step: number, steps: readonly EditorStep[]): string {
  const words = steps.find((s) => s.value === step)?.words;
  return words ? `${step}, ${words}` : String(step);
}

/** A level in a sentence: "LTS 3, for experienced cyclists" or "Avoid". */
export function levelPhrase(step: number, steps: readonly EditorStep[]): string {
  const words = steps.find((s) => s.value === step)?.words ?? "";
  if (step === 5) return "Avoid";
  return words ? `LTS ${step}, ${words[0].toLowerCase()}${words.slice(1)}` : `LTS ${step}`;
}

/** Where the road's level now comes from, said once above the slider. */
export function currentText(current: EditorCurrent, steps: readonly EditorStep[]): string {
  const level = levelPhrase(current.step, steps);
  const floor = current.at_least ? " (a floor: at least this)" : "";
  switch (current.source) {
    case "classifier":
      return `Now ${level}, from RouteMaker's classifier.`;
    case "file":
      return `Now ${level}${floor}, from a reviewed override.`;
    case "admin":
      return `Now ${level}${floor}, from an override typed in the admin.`;
    case "panel": {
      const who =
        current.by === "you" ? "your change" : current.by === "another admin" ? "another admin's change" : "a change made here";
      const when = current.when ? ` on ${shortDate(current.when)}` : "";
      return `Now ${level}${floor}, from ${who}${when}.`;
    }
  }
}

/** "Oct 9", from an ISO time; the empty string if it is not one. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/** The sentence after a save. */
export function savedSaid(result: EditResult, steps: readonly EditorStep[], floorOnly: boolean): string {
  const way = result.ways[0];
  const undo = `You can undo it for ${UNDO_MINUTES} minutes.`;
  if (!way) return `Saved. ${undo}`;
  if (!way.changed) {
    return floorOnly
      ? `Saved. This road is already at least that level, so nothing changed. ${undo}`
      : `Saved. This road already had ${levelPhrase(way.step, steps)}, so nothing changed on the map. ${undo}`;
  }
  return `Changed to ${levelPhrase(way.step, steps)}. ${AFTER_REBUILD} ${undo}`;
}

export function undoneSaid(result: EditResult, steps: readonly EditorStep[]): string {
  const way = result.ways[0];
  return way ? `Undone. This road is back to ${levelPhrase(way.step, steps)}.` : "Undone.";
}

export interface FormValues {
  reason: string;
  note: string;
}

export interface FormProblem {
  field: "reason" | "public_note";
  message: string;
}

/** What is wrong with the form before it is sent, or null. */
export function formProblem(values: FormValues, reasonMax: number, noteMax: number): FormProblem | null {
  const reason = values.reason.trim();
  if (!reason) return { field: "reason", message: "Enter a private reason. It is never shown to riders." };
  if (values.reason.length > reasonMax) {
    return { field: "reason", message: `The private reason is at most ${reasonMax} characters; it is ${values.reason.length}.` };
  }
  if (values.note.trim().length > noteMax) {
    return { field: "public_note", message: `The public note is at most ${noteMax} characters; it is ${values.note.trim().length}.` };
  }
  return null;
}

/** "123 of 500 characters", the counter under a text box. */
export function countText(text: string, max: number): string {
  return `${text.length} of ${max} characters`;
}

/** The `csrftoken` cookie's value, or null (Django sets it with /api/me and the editor's starting state). */
export function csrfFromCookie(cookie: string): string | null {
  for (const part of cookie.split(";")) {
    const [name, ...rest] = part.trim().split("=");
    if (name === "csrftoken") return decodeURIComponent(rest.join("="));
  }
  return null;
}

/** What the API's refusals mean to an admin: the server's own sentence where it wrote one for them. */
export function refusalText(status: number, serverMessage: string | null): string {
  if (serverMessage && [400, 403, 404, 409].includes(status)) return serverMessage;
  if (status === 401) return "You are signed out. Sign in again to change a road.";
  if (status === 429) return "Too many changes in the last hour. Wait a while and try again.";
  return "The change was not saved. Nothing was changed; try again shortly.";
}

type Fetch = typeof fetch;

/** GET /api/me, asked once per page (a sign-in leaves the page and comes back to a new one). */
let mePromise: Promise<Me> | null = null;

export function forgetMe(): void {
  mePromise = null;
}

export function fetchMe(origin: string, get: Fetch = fetch): Promise<Me> {
  if (!mePromise) {
    mePromise = (async () => {
      try {
        const response = await get(`${origin}/api/me`, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(String(response.status));
        const body = (await response.json()) as Partial<Me>;
        return {
          signed_in: body.signed_in === true,
          can_change_lts: body.can_change_lts === true,
          can_suggest: body.can_suggest === true,
        };
      } catch {
        // Not cached: the next panel asks again. Until then nobody is offered the editor.
        mePromise = null;
        return NO_ME;
      }
    })();
  }
  return mePromise;
}

async function errorBody(response: Response): Promise<{ message: string | null; field: string | null; code: string | null }> {
  try {
    const body = (await response.json()) as { error?: unknown; field?: unknown; code?: unknown };
    return {
      message: typeof body.error === "string" ? body.error : null,
      field: typeof body.field === "string" ? body.field : null,
      code: typeof body.code === "string" ? body.code : null,
    };
  } catch {
    return { message: null, field: null, code: null };
  }
}

/** GET /api/stress-edits/way/{id}. */
export async function fetchEditorState(
  origin: string,
  wayId: number,
  signal?: AbortSignal,
  get: Fetch = fetch,
): Promise<EditorLoad> {
  try {
    const response = await get(`${origin}/api/stress-edits/way/${wayId}`, {
      signal,
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      const body = await errorBody(response);
      return { kind: "error", message: refusalText(response.status, body.message) };
    }
    return { kind: "ready", state: (await response.json()) as EditorState };
  } catch (error) {
    if ((error as { name?: string })?.name === "AbortError") throw error;
    return { kind: "error", message: refusalText(500, null) };
  }
}

async function send(url: string, payload: unknown, csrf: string | null, post: Fetch): Promise<SaveOutcome> {
  try {
    const response = await post(url, {
      method: "POST",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        ...(csrf ? { "X-CSRFToken": csrf } : {}),
      },
      body: JSON.stringify(payload),
    });
    if (response.ok) return { kind: "saved", result: (await response.json()) as EditResult };
    const body = await errorBody(response);
    return {
      kind: "refused",
      status: response.status,
      message: refusalText(response.status, body.message),
      field: body.field,
      code: body.code,
    };
  } catch {
    return { kind: "refused", status: 0, message: refusalText(0, null), field: null, code: null };
  }
}

/** POST /api/stress-edits. */
export function saveEdit(origin: string, request: SaveRequest, csrf: string | null, post: Fetch = fetch): Promise<SaveOutcome> {
  return send(`${origin}/api/stress-edits`, request, csrf, post);
}

/** POST /api/stress-edits/{id}/undo. */
export function undoEdit(origin: string, id: number, csrf: string | null, post: Fetch = fetch): Promise<SaveOutcome> {
  return send(`${origin}/api/stress-edits/${id}/undo`, {}, csrf, post);
}
