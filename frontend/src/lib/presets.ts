/**
 * The presets the public planner offers, as the SHARED API CONTRACT names them.
 *
 * The API owns what each preset does (src/core/presets.py, one module); this is
 * only the picker's list and the sentence that explains each one, so a rider
 * does not have to know the vocabulary (PLAN.md, First run).
 */

/**
 * The ride types that reach a place on foot, with no bike of your own (Stephen 2026-10-19): Bikeshare docks the bike
 * and walks on, and Bikeshare + walk, train or bus walks or docks too. A Metro station is then reached by its
 * nearest entrance, not the elevator a bike needs (railStations.ts, walkEntrance).
 */
export const endsOnFoot = (preset: PresetId): boolean => preset === "bikeshare" || preset === "bikeshare-transit";

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
  | "novice"
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
  /**
   * The gist in one short sentence, for Go's More ride types (Stephen, 2026-10-15: "a popout that
   * has all these options and explains things more"); the detail stays in `description`.
   */
  summary: string;
}

export const PRESETS: readonly PresetOption[] = [
  {
    id: "default",
    label: "Default",
    description: "Everyday riding that prefers paths and quiet streets, even when a busier road would be faster.",
    summary: "Everyday riding on paths and quiet streets.",
  },
  {
    id: "trailmaxxing",
    label: "Trailmaxxing",
    description:
      "The calmest route, aiming at your target distance: paths, protected lanes and quiet streets, with busy streets only where there is no other way. It finds the least stressful route, not the most trail, so it may add miles.",
    summary: "The calmest route, aimed at your target distance.",
  },
  {
    id: "group-ride",
    label: "Group Ride",
    description: "A group riding with traffic at riding pace: quiet roads, fewer turns and gates.",
    summary: "A group on quiet roads with few turns.",
  },
  {
    id: "mass-ride",
    label: "Mass Ride",
    description:
      "A large group taking the roadway: roads only, no trails, no bike-lane preference, never against a one-way street's traffic, few turns, at parade pace.",
    summary: "A large group taking the road at parade pace.",
  },
  {
    id: "mountain-goat",
    label: "Mountain Goat",
    description: "Looks for climbs: picks the hilliest of a few alternative routes, up to half again as long.",
    summary: "Seeks out climbs for a hillier ride.",
  },
  {
    // docs/MTB-TOPO-PLAN.md, slice 6: a ride type of its own, separate from Mountain Goat (OWNER-DECISIONS 148).
    id: "mountain-bike",
    label: "Mountain Bike",
    description:
      "Seeks mountain-bike trails up to the level you choose, joined by calm roads, as a loop from your start unless you turn the loop off. Never uses trails closed to bikes or mapped closed when wet. Times singletrack at a mountain bike's pace.",
    summary: "Trails at your level, linked by calm roads.",
  },
  {
    id: "gravel",
    label: "Gravel",
    description: "Unpaved roads and trails cost nothing extra; it does not yet seek them out.",
    summary: "Treats unpaved roads and trails like pavement.",
  },
  {
    id: "fast",
    label: "Fast",
    description: "Direct roads, few turns and smooth pavement, whatever the traffic.",
    summary: "The most direct route, whatever the traffic.",
  },
  {
    id: "cargo",
    label: "Cargo Bike",
    description:
      "A long, heavy bike, carrying cargo or with passengers (people or pets): gentle grades, no narrow barriers, times at a cargo bike's pace. With electric assist, e-bike rules and a little more speed, but hills still count.",
    summary: "Gentle hills and no narrow barriers.",
  },
  {
    id: "ebike",
    label: "E-bike",
    description: "Leaves out ways mapped as closed to e-bikes, starts fine with hills (the more direct route wins), times at assisted pace.",
    summary: "Electric assist, so hills matter less.",
  },
  {
    id: "bikeshare",
    label: "Bikeshare",
    description:
      "Walk to a dock with a bike, ride dock to dock, then walk to your destination. Choose a classic bike (hill-averse, slower) or an e-bike. Calm streets and paths first; docks are chosen from live availability where it can be read.",
    summary: "Walk to a dock, ride a shared bike, walk on.",
  },
  {
    // v0.7.0, Novice and Nervous (Stephen 2026-10-13), in Riding with kids' place (old links open it: PRESET_ALIASES).
    id: "novice",
    label: "Novice and Nervous",
    keywords: "beginner kids children calm",
    description:
      "For riders new to traffic: every road is treated as one step busier than it is, so busy streets are avoided hard, with short detours only. Where a busy street is the only way, transit or bikeshare is offered too.",
    summary: "Busy streets avoided hard, for new riders.",
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
      "Your own bike the whole way, with Metro, MARC, VRE, Light RailLink, Metro SubwayLink or a bus's bike rack: riding directly there, then the quickest transit trips by scheduled times, not live. Uses stations a bike can get into (Metro's elevators), and never leaves the bike.",
    summary: "Your bike plus a train or bus.",
  },
  {
    id: "bikeshare-transit",
    label: "Bikeshare + 🚶🚆🚌",
    spoken: "Bikeshare plus walk, train or bus",
    keywords: "transit",
    description:
      "Bikeshare directly there, walking where that is quickest or the trip is short, or transit with either end a walk or a bikeshare bike, whichever is quicker (a bike is docked before you board). Metro, MARC, VRE, Light RailLink, Metro SubwayLink and buses; scheduled times, not live; docks from live availability where it can be read.",
    summary: "Bikeshare or walking plus a train or bus.",
  },
  {
    // REBALANCE-RIDE (Stephen, 2026-10-12): an Adventure ride type; the description is his.
    id: "rebalance",
    label: "Rebalance Ride",
    description:
      "Move a bikeshare bike from a crowded station to one that needs bikes. Rides like this can earn bikeshare reward points (Bike Angels in the Capital Bikeshare app); your points show there, not here.",
    summary: "Move a shared bike where bikes are needed.",
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

/** Old ride type ids that open a ride type now named otherwise (links, saved settings, GPX, My Go). */
export const PRESET_ALIASES: Readonly<Record<string, PresetId>> = { kids: "novice" };

/** A ride type id, an old one read as the ride type it became; null when it is neither. */
export function resolvePreset(value: unknown): PresetId | null {
  if (isPreset(value)) return value;
  if (typeof value === "string" && Object.hasOwn(PRESET_ALIASES, value)) return PRESET_ALIASES[value];
  return null;
}

export function parsePreset(value: unknown): PresetId {
  return resolvePreset(value) ?? DEFAULT_PRESET;
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

/**
 * The map layers a ride type turns on when chosen (the owner, 2026-10-19: "When gravel or mtb are selected,
 * show the trails and topo automatically" and "likewise do topo and climbs for mountain goat"). Turned on,
 * not remembered as the rider's own choice, and only coming into the ride type from one without them, so the
 * rider can still turn one off while riding it (App.tsx choosePreset). Mountain Bike's pair was slice 6's
 * default (the owner's defaults of 2026-10-11).
 */
export interface RideTypeLayers {
  mtb: boolean;
  topo: boolean;
  climbs: boolean;
}

export function rideTypeLayers(id: string): RideTypeLayers {
  const offRoad = id === "mountain-bike" || id === "gravel";
  return { mtb: offRoad, topo: offRoad || id === "mountain-goat", climbs: id === "mountain-goat" };
}

/** The layers to turn on going from ride type `from` to `to`: those `to` brings that `from` did not. */
export function layersTurnedOn(from: string, to: string): RideTypeLayers {
  const was = rideTypeLayers(from);
  const now = rideTypeLayers(to);
  return { mtb: now.mtb && !was.mtb, topo: now.topo && !was.topo, climbs: now.climbs && !was.climbs };
}
