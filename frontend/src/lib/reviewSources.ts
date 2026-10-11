/**
 * What the admin's review (SuggestionReview.tsx) lists: rider suggestions of a road's traffic stress
 * (lib/suggestions.ts) and of a junction's danger level (lib/junctionSuggest.ts; OWNER-DECISIONS 232), in one
 * list, and rider-marked Mass Ride hazards (lib/massHazards.ts; FOLLOWUP-MASSRIDE-MAP part 3).
 * One review, the owner's same three actions for each (2026-10-10): Approve now, Delete, Send to Discord.
 */
import { REVIEW_HEADING, fetchSuggestions, reviewSuggestion, type ReviewAction } from "./suggestions.ts";
import { fetchJunctionSuggestions, loadProblem, reviewEntries, reviewJunctionSuggestion, type ReviewEntry } from "./junctionSuggest.ts";
import { fetchHazardReports, hazardReportLine, reviewHazard, type HazardReportItem } from "./massHazards.ts";

/** What every reviewed item has. */
export interface ReviewItem {
  id: number;
  /** What the status sentences name it by, when `place` does not say. */
  road?: string;
  /** Unique within the list when two kinds share it ("road-41", "junction-3"); else the id. */
  key?: string;
  /** "road" or "junction" in the stress list: its endpoints, and its class. */
  kind?: string;
  /** What the status sentences name it by ("the junction of Oak Street and Elm Street"). */
  place?: string;
  /** A further line in words under the heading, or "". */
  detail?: string;
  /** Said with a confirmation before Approve now goes ahead, or "" to approve at once. */
  warning?: string;
  reason: string;
  status: "pending" | "sent_to_discord";
  lat: number | null;
  lon: number | null;
}

type Reviewed<B> = { ok: true; body: B } | { ok: false; message: string };

/** A list that came in part: what came, and a sentence naming what did not. */
export interface PartLoaded<T> {
  items: T[];
  problem: string;
}

export const itemKey = (item: ReviewItem): string => item.key ?? String(item.id);
export const itemPlace = (item: ReviewItem): string => item.place ?? item.road ?? "";

export interface ReviewSource<T extends ReviewItem> {
  /** Distinguishes the sections' ids. */
  key: string;
  heading: string;
  intro: string;
  listLabel: string;
  none: string;
  show: string;
  refresh: string;
  deleteQuestion: string;
  /** "suggestion" or "hazard report": the status sentences' noun. */
  noun: string;
  /** Approve now changes the stress map, whose tiles are then asked for again. */
  stress: boolean;
  fetch(origin: string): Promise<T[] | string | PartLoaded<T>>;
  review<B>(origin: string, item: T, action: ReviewAction, csrf: string | null): Promise<Reviewed<B>>;
  line(item: T): string;
}

/** Roads' and junctions' suggestions, one list oldest first; a list that did not load is named. */
async function fetchStress(origin: string): Promise<ReviewEntry[] | string | PartLoaded<ReviewEntry>> {
  const [roads, junctions] = await Promise.all([fetchSuggestions(origin), fetchJunctionSuggestions(origin)]);
  const problem = loadProblem(roads, junctions);
  if (typeof roads === "string" && typeof junctions === "string") return problem;
  const items = reviewEntries(typeof roads === "string" ? [] : roads, typeof junctions === "string" ? [] : junctions);
  return problem ? { items, problem } : items;
}

export const STRESS_REVIEW: ReviewSource<ReviewEntry> = {
  key: "stress",
  heading: REVIEW_HEADING,
  intro:
    "Riders' suggested levels for roads and junctions wait here. Approve now changes the road at once, or the junction for every route planned from then on; Send to Discord gives you a poll to paste into any bike group and keeps the suggestion here to approve or delete later.",
  listLabel: "Suggestions waiting",
  none: "No suggestions are waiting.",
  show: "Show suggestions",
  refresh: "Refresh suggestions",
  deleteQuestion: "Delete this suggestion? It cannot be brought back.",
  noun: "suggestion",
  stress: true,
  fetch: fetchStress,
  review: <B,>(origin: string, item: ReviewEntry, action: ReviewAction, csrf: string | null) =>
    item.kind === "junction" ? reviewJunctionSuggestion<B>(origin, item.id, action, csrf) : reviewSuggestion<B>(origin, item.id, action, csrf),
  line: (item) => item.line,
};

export const HAZARD_REVIEW: ReviewSource<HazardReportItem> = {
  key: "hazard",
  heading: "Mass Ride hazard reports",
  intro:
    "Riders' Caution and Warning reports for the Mass Ride map wait here. Approve now puts the hazard on the Mass Ride map at once; Send to Discord gives you a poll to paste and keeps the report here to approve or delete later.",
  listLabel: "Hazard reports waiting",
  none: "No hazard reports are waiting.",
  show: "Show hazard reports",
  refresh: "Refresh hazard reports",
  deleteQuestion: "Delete this hazard report? It cannot be brought back.",
  noun: "report",
  stress: false,
  fetch: (origin) => fetchHazardReports(origin),
  review: <B,>(origin: string, item: HazardReportItem, action: ReviewAction, csrf: string | null) => reviewHazard<B>(origin, item.id, action, csrf),
  line: hazardReportLine,
};
