/**
 * The one-line summary of the ride settings, for the sidebar's "Ride" button
 * (OWNER-DECISIONS 312, mockup v3): "Default · quiet streets · hills up to 8% ·
 * now". It names the ride type, what the Traffic and Hills sliders are set to,
 * and when; a target distance ("about 20 mi (32.2 km)", miles first), a loop or
 * "avoid gravel" is added only when it is set. It never
 * says the rider and bike weight, which is private (313-314): that has its own
 * line, status only, in the expanded settings.
 *
 * The same parts are shown joined with a middle dot and read joined with
 * commas (`rideSummarySpoken`), so a screen reader does not say "middle dot".
 */
import { CARRYINGS, WHENS, fitTarget, hillsGradePosition, seeksClimbs, stressMax, trailsOffLocked, whenInSentence, type Dials } from "./dials.ts";
import { formatDistance } from "./format.ts";
import { presetLabel, presetSaid, type PresetId } from "./presets.ts";
import { isCustom } from "./rideTypeDialog.ts";
import { t } from "./i18n.ts";

/** The traffic slider's position in two or three words. */
export function trafficShort(stress: number): string {
  if (stress <= 10) return t("traffic tolerant");
  if (stress < 30) return t("direct");
  if (stress <= 50) return t("balanced traffic");
  if (stress < 75) return t("quiet streets");
  if (stress <= 80) return t("low stress");
  if (stress < 95) return t("calm");
  return t("calmest");
}

/**
 * The hills slider's position, as the slider says it (`hillsWords`, review N1): the grade it sets, "hills up to 8%";
 * Mountain Goat's right half, "some extra climbing" or "seeks hills".
 */
export function hillsShort(hills: number, climbs: boolean): string {
  if (climbs && hills > 10) return hills < 80 ? t("some extra climbing") : t("seeks hills");
  return t("hills up to {grade}%", { grade: hillsGradePosition(hills) });
}

/** The ride time: "now" for "when I'm planning", else the option's own words, first letter lowered. */
export function whenShort(when: Dials["when"]): string {
  if (when === null) return t("now");
  const label = WHENS.find((option) => option.id === when)?.label;
  return label ? whenInSentence(label) : t("now");
}

/** The ride type as the summary names it: "Default", "Custom (based on Default)", with its load and assist. */
export function rideTypeShort(preset: PresetId, dials: Dials, name: (id: PresetId) => string = presetLabel): string {
  const carrying = CARRYINGS.find((c) => c.id === dials.carrying);
  return (
    (isCustom(preset, dials) ? t("Custom (based on {type})", { type: name(preset) }) : name(preset)) +
    (carrying ? `, ${carrying.label.toLowerCase()}` : "") +
    (dials.assist ? t(", electric assist") : "")
  );
}

/** A set target distance, miles first: "about 20.0 mi (32.2 km)"; null with none. */
export function targetShort(metres: Dials["targetDistanceM"]): string | null {
  const target = fitTarget(metres);
  return target === undefined ? null : t("about {distance}", { distance: formatDistance(target) });
}

/** The summary's parts, in order (312's: ride type, traffic and hills, when, target distance, loop, roads only, gravel). */
export function rideSummaryParts(preset: PresetId, dials: Dials, name: (id: PresetId) => string = presetLabel): string[] {
  const locked = stressMax(preset) === 0;
  const target = targetShort(dials.targetDistanceM);
  return [
    rideTypeShort(preset, dials, name),
    locked ? t("most direct roadway") : trafficShort(dials.stress),
    hillsShort(dials.hills, seeksClimbs(preset)),
    whenShort(dials.when),
    ...(target ? [target] : []),
    ...(dials.loop === true && preset !== "mass-ride" ? [t("loop")] : []),
    ...(dials.trailsOff === true && !trailsOffLocked(preset) ? [t("roads only")] : []),
    ...(dials.avoidGravel === true ? [t("avoids gravel")] : []),
  ];
}

/** What is shown: "Default · quiet streets · hills up to 8% · now". */
export function rideSummary(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials).join(" · ");
}

/** What is read: the same parts with commas. */
export function rideSummarySpoken(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials, presetSaid).join(", ");
}

/**
 * The Ride settings line's words (edit-route redesign, Stephen 2026-10-18): the summary without the ride type, which
 * has its own button above it ("quiet streets · hills up to 8% · now").
 */
export function settingsSummary(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials).slice(1).join(" · ");
}

/** The same, as read: joined with commas. */
export function settingsSummarySpoken(preset: PresetId, dials: Dials): string {
  return rideSummaryParts(preset, dials, presetSaid).slice(1).join(", ");
}
