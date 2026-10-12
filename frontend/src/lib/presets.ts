/**
 * The presets the public planner offers, as the SHARED API CONTRACT names them.
 *
 * The API owns what each preset does (src/core/presets.py, one module); this is
 * only the picker's list and the sentence that explains each one, so a rider
 * does not have to know the vocabulary (PLAN.md, First run).
 */

export type PresetId =
  | "default"
  | "trailmaxxing"
  | "group-ride"
  | "mass-ride"
  | "mountain-goat"
  | "mountain-bike"
  | "gravel"
  | "fast"
  | "cargo"
  | "ebike"
  | "bikeshare"
  | "kids"
  | "bike-transit"
  | "bikeshare-transit"
  | "rebalance";

export interface PresetOption {
  id: PresetId;
  /** The name as it shows; it may carry emoji (the transit types), which are never read out. */
  label: string;
  /** The name a screen reader says, where the label has emoji: "Bikeshare plus walk, train or bus". */
  spoken?: string;
  /** More words the ride type search finds it by ("transit"), never shown. */
  keywords?: string;
  /** What the ride type does today, in plain words; nothing it does not do yet. */
  description: string;
}

export const PRESETS: readonly PresetOption[] = [
  {
    id: "default",
    label: "Default",
    description: "Everyday riding that prefers paths and quiet streets, even when a busier road would be faster.",
  },
  {
    id: "trailmaxxing",
    label: "Trailmaxxing",
    description:
      "The calmest route, aiming at your target distance: paths, protected lanes and quiet streets, with busy streets only where there is no other way. It finds the least stressful route, not the most trail, so it may add miles.",
  },
  {
    id: "group-ride",
    label: "Group Ride",
    description: "A group riding with traffic at riding pace: quiet roads, fewer turns and gates.",
  },
  {
    id: "mass-ride",
    label: "Mass Ride",
    description:
      "A large group taking the roadway: roads only, no trails, no bike-lane preference, never against a one-way street's traffic, few turns, at parade pace.",
  },
  {
    id: "mountain-goat",
    label: "Mountain Goat",
    description: "Looks for climbs: picks the hilliest of a few alternative routes, up to half again as long.",
  },
  {
    // docs/MTB-TOPO-PLAN.md, slice 6: a ride type of its own, separate from Mountain Goat (OWNER-DECISIONS 148).
    id: "mountain-bike",
    label: "Mountain Bike",
    description:
      "Seeks mountain-bike trails up to the level you choose, joined by calm roads, as a loop from your start unless you turn the loop off. Never uses trails closed to bikes or mapped closed when wet. Times singletrack at a mountain bike's pace.",
  },
  {
    id: "gravel",
    label: "Gravel",
    description: "Unpaved roads and trails cost nothing extra; it does not yet seek them out.",
  },
  {
    id: "fast",
    label: "Fast",
    description: "Direct roads, few turns and smooth pavement, whatever the traffic.",
  },
  {
    id: "cargo",
    label: "Cargo Bike",
    description:
      "A long, heavy bike, carrying cargo or with passengers (people or pets): gentle grades, no narrow barriers, times at a cargo bike's pace. With electric assist, e-bike rules and a little more speed, but hills still count.",
  },
  {
    id: "ebike",
    label: "E-bike",
    description: "Leaves out ways mapped as closed to e-bikes, starts fine with hills (the more direct route wins), times at assisted pace.",
  },
  {
    id: "bikeshare",
    label: "Bikeshare",
    description:
      "Walk to a dock with a bike, ride dock to dock, then walk to your destination. Choose a classic bike (hill-averse, slower) or an e-bike. Calm streets and paths first; docks are chosen from live availability where it can be read.",
  },
  {
    // FOLLOWUP-KIDS-PRESET (OWNER-DECISIONS 240 (B)): children on their own bikes.
    id: "kids",
    label: "Riding with kids",
    description:
      "Children on their own bikes: paths and the quietest streets strongly preferred, other quiet streets only when they save a real detour, busy streets avoided hard. Gentler hills, and times at a child's pace.",
  },
  {
    // TRANSIT-ASSIST (Stephen, 2026-10-12): transit is two commuting ride types, chosen like any other.
    // Renamed with emoji that evening (20:35): the emoji are aria-hidden wherever the name shows
    // (PresetName), and `spoken` is the name a screen reader hears. The ids and links are unchanged.
    id: "bike-transit",
    label: "Own Bike + 🚆🚌",
    spoken: "Own bike plus train or bus",
    keywords: "transit",
    description:
      "Your own bike the whole way, with Metro, MARC, Light RailLink, Metro SubwayLink or a bus's bike rack: riding directly there, then the quickest transit trips by scheduled times, not live. Uses stations a bike can get into (Metro's elevators), and never leaves the bike.",
  },
  {
    id: "bikeshare-transit",
    label: "Bikeshare + 🚶🚆🚌",
    spoken: "Bikeshare plus walk, train or bus",
    keywords: "transit",
    description:
      "Bikeshare directly there, walking where that is quickest or the trip is short, or transit with either end a walk or a bikeshare bike, whichever is quicker (a bike is docked before you board). Metro, MARC, Light RailLink, Metro SubwayLink and buses; scheduled times, not live; docks from live availability where it can be read.",
  },
  {
    // REBALANCE-RIDE (Stephen, 2026-10-12): an Adventure ride type; the description is his.
    id: "rebalance",
    label: "Rebalance Ride",
    description:
      "Move a bikeshare bike from a crowded station to one that needs bikes. Rides like this can earn bikeshare reward points (Bike Angels in the Capital Bikeshare app); your points show there, not here.",
  },
];

/** The transit ride types (lib/transit.ts): a start and an end, no loop, the trip in steps. */
export const TRANSIT_PRESETS: readonly PresetId[] = ["bike-transit", "bikeshare-transit"];

export function isTransit(id: PresetId): boolean {
  return TRANSIT_PRESETS.includes(id);
}

/** The ride types planned as a bikeshare trip (core.bikeshare): Bikeshare and Rebalance Ride. */
export const BIKESHARE_PRESETS: readonly PresetId[] = ["bikeshare", "rebalance"];

export function usesBikeshare(id: PresetId): boolean {
  return BIKESHARE_PRESETS.includes(id);
}

/** Ride types planned from a start and an end only (no loop, no stops): the bikeshare and transit types. */
export function twoPointsOnly(id: PresetId): boolean {
  return usesBikeshare(id) || isTransit(id);
}

export const DEFAULT_PRESET: PresetId = "default";

export function isPreset(value: unknown): value is PresetId {
  return typeof value === "string" && PRESETS.some((p) => p.id === value);
}

export function parsePreset(value: unknown): PresetId {
  return isPreset(value) ? value : DEFAULT_PRESET;
}

/** The name as it shows (it may carry emoji: show it with PresetName, which hides them from a screen reader). */
export function presetLabel(id: PresetId): string {
  return PRESETS.find((p) => p.id === id)?.label ?? id;
}

/** The name in words, for anything said or written as plain text (announcements, shared text, aria-labels). */
export function presetSaid(id: PresetId): string {
  const option = PRESETS.find((p) => p.id === id);
  return option?.spoken ?? option?.label ?? id;
}
