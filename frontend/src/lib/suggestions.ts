/**
 * Rider suggestions (OWNER-DECISIONS 441h, 460.4, 460.5; core/suggestions.py) and the admin's review.
 *
 * A rider the settings allow (`Me.can_suggest`) suggests a level for the road piece in the road panel;
 * nothing changes on the map until an instance admin reviews it. The admin's three actions (the owner,
 * 2026-10-10): approve now (live at once, as the editor's change), delete, or send to Discord: a
 * ready-to-paste plain-English poll with a Copy button that says "Copied" (the copy is the action that
 * is always there; "I like the fallback because I can also poll one of several bike groups I'm a part
 * of"), and the suggestion is marked as sent so it can be approved or deleted later.
 */
import { stepLabel } from "./stressEditor.ts";

/** Every step's words (core/segment_info.py STEP_WORDS; OWNER-DECISIONS 441i, 441l). */
export const STEP_WORDS: Readonly<Record<string, string>> = {
  "1": "Comfortable for everyone",
  "1.5": "Probably comfortable for older children",
  "2": "Fine for adults",
  "2.5": "Fine for most confident adults",
  "3": "For experienced cyclists",
  "3.5": "Stressful even for experienced cyclists",
  "4": "High stress: busy, fast traffic",
  "4.5": "A very high-stress road",
  "5": "Avoid",
};

export const SUGGEST_TEXT = "Suggest a change";
export const SUGGEST_HEADING = "Suggest a traffic stress level";
export const SUGGEST_LEVEL_LABEL = "The level you suggest";
export const SUGGEST_REASON_LABEL = "Why (required)";
export const SUGGEST_REASON_MAX = 500;
export const SUGGEST_PRIVACY =
  "An admin reviews every suggestion before anything changes. The road's location and your reason may be shared in a public poll to ask other riders, never your name or the spot you clicked.";
export const SUGGEST_SEND = "Send suggestion";
export const REVIEW_HEADING = "Rider suggestions";
export const COPY_POST = "Copy post";
export const COPIED = "Copied";
export const COPY_FAILED = "Could not copy. Select the post and copy it yourself.";

/** A step and its words, as the slider reads it: "2.5, Fine for most confident adults". */
export function suggestValueText(step: number): string {
  const words = STEP_WORDS[stepLabel(step)];
  return words ? `${stepLabel(step)}, ${words}` : stepLabel(step);
}

export interface SuggestRequest {
  osm_way_id: number;
  lat: number;
  lon: number;
  step: number;
  reason: string;
}

export type SuggestOutcome =
  | { kind: "sent"; message: string }
  | { kind: "refused"; status: number; message: string; field: string | null };

export interface SuggestionItem {
  id: number;
  osm_way_id: number;
  road: string;
  lat: number;
  lon: number;
  current_step: number;
  current_words: string;
  step: number;
  words: string;
  reason: string;
  status: "pending" | "sent_to_discord";
  created_at: string;
  sent_at: string | null;
}

export interface DiscordPost {
  id: number;
  status: string;
  post: string;
  characters: number;
  options: { letter: string; label: string; tier: number | null }[];
}

type Fetch = typeof fetch;

/** The form's own check before sending: the field and its sentence, or null. */
export function suggestProblem(reason: string): { field: "reason"; message: string } | null {
  const text = reason.trim();
  if (!text) return { field: "reason", message: "Say why, in a sentence or two." };
  if (text.length > SUGGEST_REASON_MAX) {
    return { field: "reason", message: `The reason is at most ${SUGGEST_REASON_MAX} characters.` };
  }
  return null;
}

function refused(status: number, message: string | null): string {
  if (message && [400, 403, 404, 409].includes(status)) return message;
  if (status === 401) return "You are signed out. Sign in again.";
  if (status === 429) return "Too many in the last hour. Wait a while and try again.";
  return "Nothing was sent. Try again shortly.";
}

/** One JSON call to the suggestion endpoints: the body, or the status and its sentence (and the field it names). */
export async function call<T>(
  url: string,
  init: RequestInit,
  csrf: string | null,
  run: Fetch,
): Promise<{ ok: true; body: T } | { ok: false; status: number; message: string; field: string | null }> {
  try {
    const response = await run(url, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(init.method === "POST" ? { "Content-Type": "application/json" } : {}),
        ...(csrf ? { "X-CSRFToken": csrf } : {}),
      },
    });
    if (response.ok) return { ok: true, body: (await response.json()) as T };
    let message: string | null = null;
    let field: string | null = null;
    try {
      const body = (await response.json()) as { error?: unknown; field?: unknown };
      message = typeof body.error === "string" ? body.error : null;
      field = typeof body.field === "string" ? body.field : null;
    } catch {
      // No JSON: the status says it.
    }
    return { ok: false, status: response.status, message: refused(response.status, message), field };
  } catch {
    return { ok: false, status: 0, message: refused(0, null), field: null };
  }
}

/** POST /api/stress-suggestions. */
export async function sendSuggestion(origin: string, request: SuggestRequest, csrf: string | null, run: Fetch = fetch): Promise<SuggestOutcome> {
  const r = await call<{ message: string }>(`${origin}/api/stress-suggestions`, { method: "POST", body: JSON.stringify(request) }, csrf, run);
  return r.ok ? { kind: "sent", message: r.body.message } : { kind: "refused", status: r.status, message: r.message, field: r.field };
}

/** GET /api/stress-suggestions/open (instance admin). */
export async function fetchSuggestions(origin: string, run: Fetch = fetch): Promise<SuggestionItem[] | string> {
  const r = await call<{ suggestions: SuggestionItem[] }>(`${origin}/api/stress-suggestions/open`, { method: "GET" }, null, run);
  return r.ok ? r.body.suggestions : r.message;
}

export type ReviewAction = "approve" | "delete" | "discord";

/** POST /api/stress-suggestions/{id}/{action} (instance admin). */
export async function reviewSuggestion<T = { message: string; status: string; generation?: number | null }>(
  origin: string,
  id: number,
  action: ReviewAction,
  csrf: string | null,
  run: Fetch = fetch,
): Promise<{ ok: true; body: T } | { ok: false; message: string }> {
  const r = await call<T>(`${origin}/api/stress-suggestions/${id}/${action}`, { method: "POST", body: "{}" }, csrf, run);
  return r.ok ? r : { ok: false, message: r.message };
}

/** A suggestion in one line for its heading: "Oak Street: from For experienced cyclists to Fine for adults". */
export function suggestionLine(item: SuggestionItem): string {
  return `${item.road}: from ${levelName(item.current_step, item.current_words)} to ${levelName(item.step, item.words)}`;
}

function levelName(step: number, words: string): string {
  return step === 5 ? "Avoid" : `LTS ${stepLabel(step)} (${words})`;
}

/** The map link the admin's Show on map uses: the app's own `#at=lon,lat` (lib/planHash.ts). */
export function mapLink(origin: string, item: Pick<SuggestionItem, "lat" | "lon">): string {
  return `${origin}/#at=${item.lon.toFixed(5)},${item.lat.toFixed(5)}`;
}
