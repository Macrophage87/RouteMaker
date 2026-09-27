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
  | "gravel"
  | "beginner"
  | "fast"
  | "recovery"
  | "cargo"
  | "ebike"
  | "bikepacking";

export interface PresetOption {
  id: PresetId;
  label: string;
  /** What the ride type does today, in plain words; nothing it does not do yet. */
  description: string;
}

export const PRESETS: readonly PresetOption[] = [
  {
    id: "default",
    label: "Default",
    description: "Everyday riding that prefers paths and quiet streets, even when a busier road would be a little faster.",
  },
  {
    id: "trailmaxxing",
    label: "Trailmaxxing",
    description: "As much trail and quiet street as possible; directness comes second, and road links between trails stay in.",
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
      "A large group taking the roadway: roads only, no trails, no bike-lane preference, few turns, at parade pace.",
  },
  {
    id: "mountain-goat",
    label: "Mountain Goat",
    description: "Looks for climbs: picks the hilliest of a few alternative routes, up to half again as long.",
  },
  {
    id: "gravel",
    label: "Gravel",
    description: "Unpaved roads and trails cost nothing extra; it does not yet seek them out.",
  },
  {
    id: "beginner",
    label: "Beginner",
    description: "Paths and protected lanes wherever they exist, gentle grades; busy streets only where there is no other way.",
  },
  {
    id: "fast",
    label: "Fast",
    description: "Direct roads, few turns and smooth pavement, whatever the traffic.",
  },
  {
    id: "recovery",
    label: "Recovery",
    description: "The flattest way there, with Default's preference for quiet streets.",
  },
  {
    id: "cargo",
    label: "Cargo Bike",
    description: "A long, heavy bike: gentle grades, no narrow barriers, times at a cargo bike's pace.",
  },
  {
    id: "ebike",
    label: "E-bike",
    description: "Leaves out ways where e-bikes are not allowed, minds hills less, times at assisted pace.",
  },
  {
    id: "bikepacking",
    label: "Bikepacking",
    description: "A loaded touring bike on mixed surfaces; finding water, food and camping is still to come.",
  },
];

export const DEFAULT_PRESET: PresetId = "default";

export function isPreset(value: unknown): value is PresetId {
  return typeof value === "string" && PRESETS.some((p) => p.id === value);
}

export function parsePreset(value: unknown): PresetId {
  return isPreset(value) ? value : DEFAULT_PRESET;
}

export function presetLabel(id: PresetId): string {
  return PRESETS.find((p) => p.id === id)?.label ?? id;
}
