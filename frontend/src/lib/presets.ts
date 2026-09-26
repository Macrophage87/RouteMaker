/**
 * The presets the public planner offers, as the SHARED API CONTRACT names them.
 *
 * The API owns what each preset does (src/core/presets.py, one module); this is
 * only the picker's list and the sentence that explains each one, so a rider
 * does not have to know the vocabulary (PLAN.md, First run).
 */

export type PresetId = "default" | "group-ride" | "mass-ride";

export interface PresetOption {
  id: PresetId;
  label: string;
  description: string;
}

export const PRESETS: readonly PresetOption[] = [
  {
    id: "default",
    label: "Default",
    description: "Everyday riding with normal cycling priorities, balancing directness and comfort.",
  },
  {
    id: "group-ride",
    label: "Group Ride",
    description: "A club ride of about twenty at riding pace, with fewer turns and gates.",
  },
  {
    id: "mass-ride",
    label: "Mass Ride",
    description:
      "A large group taking the roadway: roads only, no trails, few turns, at parade pace.",
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
