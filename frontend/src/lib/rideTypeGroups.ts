/**
 * The ride types in groups, and the search over them (RIDE-TYPE-ORGANISE).
 *
 * Stephen, 2026-10-12: "organize all the available modes in the other options so
 * they are easier to find. Maybe a search, and possibly separate into clusters:
 * Transportation, Adventure, Group", and "Fast is more likely an adventure mode."
 * Go's More ride types (the Ride sheet) and Plan's ride type dialog both use it
 * (RideTypeSearch, below); nothing else is added to either.
 */
import { t } from "./i18n.ts";
import { createElement as h, type ChangeEvent, type ReactElement } from "react";
import { PRESETS, type PresetId, type PresetOption } from "./presets.ts";

export type RideGroupId = "favorites" | "transportation" | "adventure" | "group";

export interface RideGroup {
  id: RideGroupId;
  label: string;
  ids: readonly PresetId[];
}

/** Every ride type in exactly one group, in the order the picker shows them. */
export const RIDE_GROUPS: readonly RideGroup[] = [
  {
    id: "transportation",
    label: t("Transportation"),
    ids: ["default", "bike-transit", "bikeshare-transit", "bikeshare", "cargo", "ebike", "novice"],
  },
  {
    id: "adventure",
    label: t("Adventure"),
    ids: ["fast", "trailmaxxing", "mountain-goat", "mountain-bike", "gravel", "rebalance"],
  },
  {
    id: "group",
    label: t("Group"),
    ids: ["group-ride", "mass-ride"],
  },
];

/** Lower case, with hyphens and apostrophes dropped, so "ebike" finds "E-bike". */
function fold(text: string): string {
  return text.toLowerCase().replace(/[-'’]/g, "");
}

/** Whether a ride type matches the search: every word of it is in the name (shown or spoken), its keywords, summary or description. */
export function matchesRideType(option: PresetOption, query: string): boolean {
  const words = fold(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const text = fold(`${option.label} ${option.spoken ?? ""} ${option.keywords ?? ""} ${option.summary} ${option.description}`);
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

/**
 * The rider's favorites (lib/favoriteRides.ts) as a group of their own, first, in the order they were
 * starred, and taken out of the groups they belong to, so each ride type shows once. Only the
 * favorites the groups hold (a search's matches) are kept.
 */
export function withFavorites(groups: readonly RideGroup[], favorites: readonly PresetId[]): RideGroup[] {
  const shown = new Set(groups.flatMap((g) => g.ids));
  const ids = favorites.filter((id) => shown.has(id));
  if (ids.length === 0) return [...groups];
  return [
    { id: "favorites", label: t("Favorites"), ids },
    ...groups.map((g) => ({ ...g, ids: g.ids.filter((id) => !ids.includes(id)) })).filter((g) => g.ids.length > 0),
  ];
}

/** The ride types most riders pick: Go's More ride types shows them first, the groups folded under (review F9). */
export const COMMON_RIDE_TYPES: readonly PresetId[] = ["default", "novice", "bikeshare", "bike-transit"];

/**
 * Go's More ride types: the rider's favorites, then the common ones (less the favorites), then the
 * groups (without either), folded; a search shows its matches flat, favorites first.
 */
export function rideSections(
  query: string,
  presets: readonly PresetOption[] = PRESETS,
  favorites: readonly PresetId[] = [],
): { favorites: PresetId[]; common: PresetId[]; groups: RideGroup[]; folded: boolean } {
  const known = new Set(presets.map((p) => p.id));
  const all = filterRideGroups(query, presets);
  const shown = new Set(all.flatMap((g) => g.ids));
  const favs = favorites.filter((id) => known.has(id) && shown.has(id));
  const rest = (ids: readonly PresetId[], out: readonly PresetId[]) => ids.filter((id) => !out.includes(id));
  if (query.trim() !== "") {
    return { favorites: favs, common: [], groups: all.map((g) => ({ ...g, ids: rest(g.ids, favs) })).filter((g) => g.ids.length > 0), folded: false };
  }
  const common = rest(COMMON_RIDE_TYPES.filter((id) => known.has(id)), favs);
  const taken = [...favs, ...common];
  return {
    favorites: favs,
    common,
    groups: all.map((g) => ({ ...g, ids: rest(g.ids, taken) })).filter((g) => g.ids.length > 0),
    folded: true,
  };
}

/** How many ride types the groups hold. */
export function rideTypeCount(groups: readonly RideGroup[]): number {
  return groups.reduce((sum, group) => sum + group.ids.length, 0);
}

export const NO_RIDE_TYPES_MATCH = t("No ride types match.");

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
    h("label", { htmlFor: id }, t("Search ride types")),
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
