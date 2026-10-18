/**
 * The one-line summary of the ride settings, for the sidebar's "Ride" button
 * (OWNER-DECISIONS 312, mockup v3): "Default · quiet streets · balanced hills ·
 * now". It names the ride type, what the Traffic and Hills sliders are set to,
 * and when; a target distance ("about 20 mi (32.2 km)", miles first), a loop or
 * "avoid gravel" is added only when it is set. It never
 * says the rider and bike weight, which is private (313-314): that has its own
 * line, status only, in the expanded settings.
 *
 * The same parts are shown joined with a middle dot and read joined with
 * commas (`rideSummarySpoken`), so a screen reader does not say "middle dot".
 */
import { CARRYINGS, WHENS, fitTarget, seeksClimbs, stressMax, trailsOffLocked, whenInSentence, type Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import { presetLabel, presetSaid, type PresetId } from "./presets.ts";
import { isCustom } from "./rideTypeDialog.ts";

/** The traffic slider's position in two or three words. */
export function trafficShort(stress: number): string {
  if (stress <= 10) return "traffic tolerant";
  if (stress < 30) return "direct";
  if (stress <= 50) return "balanced traffic";
  if (stress < 75) return "quiet streets";
  if (stress <= 80) return "low stress";
  if (stress < 95) return "calm";
  return "calmest";
}

/** The hills slider's position in two words; right of the middle, by ride type (242, `hillsWords`). */
export function hillsShort(hills: number, climbs: boolean): string {
  if (hills <= -80) return "avoids hills";
  if (hills < -10) return "gentler hills";
  if (hills <= 10) return "balanced hills";
  if (!climbs) return hills < 80 ? "hills matter less" : "fine with hills";
  if (hills < 80) return "some climbing";
  return "seeks hills";
}

/** The ride time: "now" for "when I'm planning", else the option's own words, first letter lowered. */
export function whenShort(when: Dials["when"]): string {
  if (when === null) return "now";
  const label = WHENS.find((option) => option.id === when)?.label;
  return label ? whenInSentence(label) : "now";
}

/** The ride type as the summary names it: "Default", "Custom (based on Default)", with its load and assist. */
export function rideTypeShort(preset: PresetId, dials: Dials, name: (id: PresetId) => string = presetLabel): string {
  const carrying = CARRYINGS.find((c) => c.id === dials.carrying);
  return (
    (isCustom(preset, dials) ? `Custom (based on ${name(preset)})` : name(preset)) +
    (carrying ? `, ${carrying.label.toLowerCase()}` : "") +
    (dials.assist ? ", electric assist" : "")
  );
}

/** A set target distance, miles first: "about 20.0 mi (32.2 km)"; null with none. */
export function targetShort(metres: Dials["targetDistanceM"]): string | null {
  const target = fitTarget(metres);
  return target === undefined ? null : `about ${formatDistance(target)}`;
}

/** The summary's parts, in order (312's: ride type, traffic and hills, when, target distance, loop, roads only, gravel). */
export function rideSummaryParts(preset: PresetId, dials: Dials, name: (id: PresetId) => string = presetLabel): string[] {
  const locked = stressMax(preset) === 0;
  const target = targetShort(dials.targetDistanceM);
  return [
    rideTypeShort(preset, dials, name),
    locked ? "most direct roadway" : trafficShort(dials.stress),
    hillsShort(dials.hills, seeksClimbs(preset)),
    whenShort(dials.when),
    ...(target ? [target] : []),
    ...(dials.loop === true && preset !== "mass-ride" ? ["loop"] : []),
    ...(dials.trailsOff === true && !trailsOffLocked(preset) ? ["roads only"] : []),
    ...(dials.avoidGravel === true ? ["avoids gravel"] : []),
  ];
}

/** What is shown: "Default · quiet streets · balanced hills · now". */
export function rideSummary(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials).join(" · ");
}

/** What is read: the same parts with commas. */
export function rideSummarySpoken(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials, presetSaid).join(", ");
}

/**
 * The Ride settings line's words (edit-route redesign, Stephen 2026-10-18): the summary without the ride type, which
 * has its own button above it ("quiet streets · balanced hills · now").
 */
export function settingsSummary(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials).slice(1).join(" · ");
}

/** The same, as read: joined with commas. */
export function settingsSummarySpoken(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials, presetSaid).slice(1).join(", ");
}
