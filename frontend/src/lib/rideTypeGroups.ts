/**
 * The ride types in groups, and the search over them (RIDE-TYPE-ORGANISE).
 *
 * Stephen, 2026-10-12: "organize all the available modes in the other options so
 * they are easier to find. Maybe a search, and possibly separate into clusters:
 * Transportation, Adventure, Group", and "Fast is more likely an adventure mode."
 * Go's More ride types (the Ride sheet) and Plan's ride type dialog both use it
 * (RideTypeSearch, below); nothing else is added to either.
 */
import { createElement as h, type ChangeEvent, type ReactElement } from "react";
import { PRESETS, type PresetId, type PresetOption } from "./presets.ts";

export type RideGroupId = "transportation" | "adventure" | "group";

export interface RideGroup {
  id: RideGroupId;
  label: string;
  ids: readonly PresetId[];
}

/** Every ride type in exactly one group, in the order the picker shows them. */
export const RIDE_GROUPS: readonly RideGroup[] = [
  {
    id: "transportation",
    label: "Transportation",
    ids: ["default", "bike-transit", "bikeshare-transit", "bikeshare", "cargo", "ebike", "kids"],
  },
  {
    id: "adventure",
    label: "Adventure",
    ids: ["fast", "trailmaxxing", "mountain-goat", "mountain-bike", "gravel", "rebalance"],
  },
  {
    id: "group",
    label: "Group",
    ids: ["group-ride", "mass-ride"],
  },
];

/** Lower case, with hyphens and apostrophes dropped, so "ebike" finds "E-bike". */
function fold(text: string): string {
  return text.toLowerCase().replace(/[-'’]/g, "");
}

/** Whether a ride type matches the search: every word of it is in the name (shown or spoken), its keywords or the description. */
export function matchesRideType(option: PresetOption, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = fold(`${option.label} ${option.spoken ?? ""} ${option.keywords ?? ""} ${option.description}`);
  return words.every((word) => text.includes(word));
}

/** The groups with the ride types that match, in order; a group with none left out. */
export function filterRideGroups(query: string, presets: readonly PresetOption[] = PRESETS): RideGroup[] {
  const byId = new Map(presets.map((p) => [p.id, p]));
  return RIDE_GROUPS.map((group) => ({
    ...group,
    ids: group.ids.filter((id) => {
      const option = byId.get(id);
      return option !== undefined && matchesRideType(option, query);
    }),
  })).filter((group) => group.ids.length > 0);
}

/** How many ride types the groups hold. */
export function rideTypeCount(groups: readonly RideGroup[]): number {
  return groups.reduce((sum, group) => sum + group.ids.length, 0);
}

export const NO_RIDE_TYPES_MATCH = "No ride types match.";

/** What the search's status says (politely, to a screen reader): nothing until something is typed. */
export function rideTypeCountSaid(count: number, query: string): string {
  if (query.trim() === "") return "";
  if (count === 0) return NO_RIDE_TYPES_MATCH;
  return count === 1 ? "1 ride type matches." : `${count} ride types match.`;
}

/**
 * The search box: a labelled search field and a polite status saying how many
 * ride types match; when none do, the status is shown as well as said. A
 * createElement component, so a test renders it (node's runner reads .ts, not .tsx).
 */
export function RideTypeSearch({
  id,
  query,
  onQuery,
  count,
}: {
  /** The input's id (the label points at it); one per place it is used. */
  id: string;
  query: string;
  onQuery: (query: string) => void;
  count: number;
}): ReactElement {
  const said = rideTypeCountSaid(count, query);
  return h(
    "div",
    { className: "ride-type-search" },
    h("label", { htmlFor: id }, "Search ride types"),
    h("input", {
      id,
      type: "search",
      autoComplete: "off",
      spellCheck: false,
      value: query,
      onChange: (event: ChangeEvent<HTMLInputElement>) => onQuery(event.target.value),
    }),
    h("p", { role: "status", "aria-live": "polite", className: count === 0 && said ? "hint ride-type-none" : "visually-hidden" }, said),
  );
}
