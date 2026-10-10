/**
 * What the admin's review (SuggestionReview.tsx) lists: rider suggestions of a road's traffic stress
 * (lib/suggestions.ts) and rider-marked Mass Ride hazards (lib/massHazards.ts; FOLLOWUP-MASSRIDE-MAP part 3).
 * One review, the owner's same three actions for each (2026-10-10): Approve now, Delete, Send to Discord.
 */
import {
  REVIEW_HEADING,
  fetchSuggestions,
  reviewSuggestion,
  suggestionLine,
  type ReviewAction,
  type SuggestionItem,
} from "./suggestions.ts";
import { fetchHazardReports, hazardReportLine, reviewHazard, type HazardReportItem } from "./massHazards.ts";

/** What every reviewed item has. */
export interface ReviewItem {
  id: number;
  road: string;
  reason: string;
  status: "pending" | "sent_to_discord";
  lat: number | null;
  lon: number | null;
}

type Reviewed<B> = { ok: true; body: B } | { ok: false; message: string };

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
  fetch(origin: string): Promise<T[] | string>;
  review<B>(origin: string, id: number, action: ReviewAction, csrf: string | null): Promise<Reviewed<B>>;
  line(item: T): string;
}

export const STRESS_REVIEW: ReviewSource<SuggestionItem> = {
  key: "stress",
  heading: REVIEW_HEADING,
  intro:
    "Riders' suggested levels wait here. Approve now changes the road at once; Send to Discord gives you a poll to paste into any bike group and keeps the suggestion here to approve or delete later.",
  listLabel: "Suggestions waiting",
  none: "No suggestions are waiting.",
  show: "Show suggestions",
  refresh: "Refresh suggestions",
  deleteQuestion: "Delete this suggestion? It cannot be brought back.",
  noun: "suggestion",
  stress: true,
  fetch: (origin) => fetchSuggestions(origin),
  review: <B,>(origin: string, id: number, action: ReviewAction, csrf: string | null) => reviewSuggestion<B>(origin, id, action, csrf),
  line: suggestionLine,
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
  review: <B,>(origin: string, id: number, action: ReviewAction, csrf: string | null) => reviewHazard<B>(origin, id, action, csrf),
  line: hazardReportLine,
};
