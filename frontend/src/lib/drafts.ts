/**
 * An assistant's drafts (the owner, 2026-11-09: "make the draft mcp routes an 'ephemeral' state. Something that might
 * last a week", "I want them findable, but would expire fast so as not to clutter things", "They should be listed just
 * like saved routes, just ones that disappear", and "a button in load and at the end of the ride to save the ride,
 * otherwise it's temporary"). A route an assistant app planned through RouteMaker's connector is kept seven days (our
 * default; core.models.ConnectorDraft.KEPT), each route's newest revision listed in Load route among the saved routes
 * with the days it has left and Save. Opened by its link's id, as a shared link opens; saved as any route is, with
 * `from_draft` so it is no longer listed.
 */
import { formatDistance } from "./format.ts";
import { t } from "./i18n.ts";
import { readShared } from "./sharedRoutes.ts";
import { csrfFromCookie } from "./stressEditor.ts";
import { saveRoute, type SaveOutcome, type SavedSource } from "./savedRoutes.ts";

/** One draft as GET /api/me/drafts lists it. */
export interface DraftSummary {
  /** Its link's id (a shared route's). */
  id: string;
  name: string;
  source: SavedSource;
  distance_m: number;
  preset: string;
  created_at: string;
  opened_at?: string;
  expires_at: string;
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Days a draft has left, a part day counted whole: 1 on its last day, 0 once gone. */
export function daysLeft(expiresAt: string, now: number = Date.now()): number {
  const left = new Date(expiresAt).getTime() - now;
  return Number.isNaN(left) ? 0 : Math.max(0, Math.ceil(left / DAY_MS));
}

/** "Draft, 5 days left": the row's mark, in the fewest words (Go's languages). */
export function draftLeft(expiresAt: string, now: number = Date.now()): string {
  const days = daysLeft(expiresAt, now);
  return days <= 1 ? t("Draft, last day") : t("Draft, {n} days left", { n: days });
}

/** The row's line: "4.7 mi (7.6 km) · Draft, 5 days left". */
export function draftDetails(draft: Pick<DraftSummary, "distance_m" | "expires_at">, now: number = Date.now()): string {
  return `${formatDistance(draft.distance_m)} · ${draftLeft(draft.expires_at, now)}`;
}

/** Save's aria-label on a draft's row. */
export const draftSaveLabel = (name: string) => t("Save {name} to My routes", { name });
/** Delete's (the owner, 2026-11-09: "Use the save icon, and also add delete"), with Undo for a few seconds. */
export const DRAFT_DELETE = t("Delete");
export const draftDeleteLabel = (name: string) => t("Delete {name}", { name });
export const draftDeletedSaid = (name: string) => t("Deleted {name}.", { name });

type Fetch = typeof fetch;

export async function listDrafts(origin: string, get: Fetch = fetch): Promise<DraftSummary[] | null> {
  try {
    const response = await get(`${origin}/api/me/drafts`, { headers: { Accept: "application/json" }, credentials: "same-origin" });
    if (!response.ok) return null;
    const body = (await response.json()) as { drafts?: DraftSummary[] };
    return Array.isArray(body.drafts) ? body.drafts : null;
  } catch {
    return null;
  }
}

/** Delete the draft whose link is `id`, every revision of its route with it; whether it is gone. */
export async function deleteDraft(origin: string, id: string, send: Fetch = fetch, cookie = typeof document === "undefined" ? "" : document.cookie): Promise<boolean> {
  try {
    const token = csrfFromCookie(cookie);
    const response = await send(`${origin}/api/me/drafts/${id}`, { method: "DELETE", credentials: "same-origin", headers: { Accept: "application/json", ...(token ? { "X-CSRFToken": token } : {}) } });
    return response.ok || response.status === 404;
  } catch {
    return false;
  }
}

/** Save the draft whose link is `id` to My routes, exactly as it was drafted; null when it could not be read (gone). */
export async function saveDraft(origin: string, id: string, get: Fetch = fetch, post: Fetch = fetch): Promise<SaveOutcome | null> {
  const shared = await readShared(origin, id, get);
  if (!shared || shared === "gone" || shared === "revoked") return null;
  return saveRoute(
    origin,
    {
      name: shared.name,
      source: shared.source,
      line: shared.line,
      distance_m: shared.distance_m,
      inputs: shared.inputs,
      answer: shared.answer,
      ...(shared.source === "gpx" && shared.gpx ? { gpx: shared.gpx } : {}),
      from_draft: id,
    },
    post,
  );
}

/** The draft on screen (App): its link's id, name, the length it was drafted at (a ride on it unchanged has that very
 * length) and when it goes. */
export interface OpenDraft {
  id: string;
  name: string;
  distanceM: number;
  expiresAt: string;
}
