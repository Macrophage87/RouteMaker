/**
 * The head-unit profiles a FIT or TCX course is fitted to (PLAN.md, Import and export, Formats: "Exports accept a
 * max-cue budget per device profile ... Per-profile point-count and file-size budgets sit beside the cue budget ...
 * The profile table lives in the repository with a last-verified date, defaulting to 200 course points").
 *
 * The figures are working budgets, not measured limits: none has yet been checked on the device it names
 * (`verified` is null until someone loads a course on one and records the date), so each is set no higher than
 * the most conservative figure the maker or the hubs publish. Generic is the default and no larger than any of
 * them, so a file made for it loads on any of the others.
 */

export type DeviceProfileId = "generic" | "garmin-edge" | "wahoo" | "hammerhead";

export interface DeviceProfile {
  id: DeviceProfileId;
  /** What the Device choice shows. */
  label: string;
  /** The most course points (cues) the unit keeps; older Edge units truncate past about 200 without saying. */
  maxCues: number;
  /** The most track points (records); a hub downsamples a larger course on import. */
  maxPoints: number;
  /** Characters of a course point's name the unit shows (FIT; TCX's own cap of 10 is the format's). */
  cueNameChars: number;
  /** Characters of the course's name (FIT; TCX's own cap of 15 is the format's). */
  courseNameChars: number;
  /** The date the figures were last checked on the device, or null: not yet verified on one. */
  verified: string | null;
}

export const DEVICE_PROFILES: readonly DeviceProfile[] = [
  { id: "generic", label: "Any bike computer", maxCues: 200, maxPoints: 10_000, cueNameChars: 15, courseNameChars: 15, verified: null },
  { id: "garmin-edge", label: "Garmin Edge", maxCues: 200, maxPoints: 10_000, cueNameChars: 15, courseNameChars: 15, verified: null },
  { id: "wahoo", label: "Wahoo ELEMNT", maxCues: 200, maxPoints: 20_000, cueNameChars: 32, courseNameChars: 32, verified: null },
  { id: "hammerhead", label: "Hammerhead Karoo", maxCues: 200, maxPoints: 20_000, cueNameChars: 32, courseNameChars: 32, verified: null },
];

export const DEFAULT_PROFILE: DeviceProfileId = "generic";

export function deviceProfile(id: string | null | undefined): DeviceProfile {
  return DEVICE_PROFILES.find((p) => p.id === id) ?? DEVICE_PROFILES[0];
}
