/**
 * What the dials panel and the route summary show, decided here rather than
 * in the components so it is tested without a browser (the lane has no DOM
 * harness; mutation review r1, UI1-UI5: hiding the traffic-tolerant warning,
 * unlocking Mass Ride's traffic slider or letting its hills slider seek all
 * went unnoticed while the decisions lived in DialsPanel.tsx and
 * FacilityBreakdown.tsx).
 */
import {
  AVOID_MAX_SPAN_M,
  METRES_PER_MILE,
  MILES_WORD,
  POUNDS_WORD,
  SEEK_MAX_SPAN_M,
  formatDistance,
  formatPerMile,
  formatRoughDistance,
} from "./format.ts";
import type { PresetId } from "./presets.ts";
import {
  HILLS_MIN,
  DEFAULT_MAX_RATIO,
  LONGEST_MAX_M,
  LONGEST_MIN_M,
  PASSENGERS_WEIGHT_KG,
  SYSTEM_WEIGHT_KG,
  SYSTEM_WEIGHT_MAX_KG,
  SYSTEM_WEIGHT_MIN_KG,
  STRESS_MAX,
  STRESS_MIN,
  TRAFFIC_TOLERANT_WARNING,
  calmRate,
  hillsMax,
  hillsWords,
  offersAssist,
  offersLongestRide,
  startDials,
  stressMax,
  stressWords,
  warnsTrafficTolerant,
  type Dials,
} from "./dials.ts";

export interface SliderView {
  min: number;
  max: number;
  words: string;
  ends: [string, string, string];
  disabled: boolean;
  note?: string;
}

export interface PanelView {
  /** Cargo Bike's electric-assist toggle. */
  assistToggle: boolean;
  /** The note under the toggle, while assist is on. */
  assistNote: boolean;
  traffic: SliderView;
  /** The traffic-tolerant warning under the traffic slider, or null. */
  warning: string | null;
  hills: SliderView;
  /** The "Longest ride" number input, or null where the traffic slider is not at the top. */
  longest: LongestView | null;
  /** The "System weight" number input, with it. */
  weight: WeightView | null;
  /** Where "Back to this ride type's settings" goes, or null when already there. */
  reset: Dials | null;
}

/** The "Longest ride" dial (OWNER-DECISIONS 256), in miles first, kilometres in brackets. */
export interface LongestView {
  label: string;
  /** What the input holds, in miles to a tenth; empty is the default. */
  value: string;
  min: number;
  max: number;
  /** The rule for an entry the planner will not take, as words (not a colour). */
  rule: string;
  /** Under the input: what it does, and what is set. */
  hint: string;
}

export const LONGEST_LABEL = "Longest ride (miles)";

/** The input's text for a length in metres: miles to a tenth, no trailing ".0"; empty for none. */
export function longestText(metres: number | undefined): string {
  if (metres === undefined) return "";
  const miles = Math.round((metres / METRES_PER_MILE) * 10) / 10;
  return String(miles);
}

/** Metres for what was typed in miles, or undefined for empty (the default); null where it is not a usable entry. */
export function parseLongest(text: string): number | undefined | null {
  const trimmed = text.trim().replace(/\s*(mi|miles)$/i, "");
  if (trimmed === "") return undefined;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const metres = Math.round(Number(trimmed) * METRES_PER_MILE);
  return metres >= LONGEST_MIN_M && metres <= LONGEST_MAX_M ? metres : null;
}

const LONGEST_MIN_MILES = Math.ceil((LONGEST_MIN_M / METRES_PER_MILE) * 10) / 10;
const LONGEST_MAX_MILES = Math.floor(LONGEST_MAX_M / METRES_PER_MILE);

export function longestView(dials: Dials): LongestView {
  const set = dials.maxDistanceM;
  const base =
    "Optional. The route is no longer than this, and as calm as it can be within it: " +
    "the fewest heavy-traffic roads and very high stress junctions first, then busy roads and higher stress junctions, then distance.";
  const hint =
    set === undefined
      ? `${base} Left empty, it may be up to ${DEFAULT_MAX_RATIO} times the router's own route.`
      : `${base} Set to ${formatDistance(set)}. A limit shorter than the calmest route makes it use busier roads to fit.`;
  return {
    label: LONGEST_LABEL,
    value: longestText(set),
    min: LONGEST_MIN_MILES,
    max: LONGEST_MAX_MILES,
    rule: `Enter ${LONGEST_MIN_MILES} to ${LONGEST_MAX_MILES} ${MILES_WORD}, or leave it empty.`,
    hint,
  };
}

/** The "System weight" dial (OWNER-DECISIONS 264), in pounds first, kilograms in brackets. */
export interface WeightView {
  label: string;
  /** Pounds, whole; empty is the default. */
  value: string;
  min: number;
  max: number;
  rule: string;
  hint: string;
}

export const WEIGHT_LABEL = "System weight (pounds)";
export const LB_PER_KG = 2.20462;

export function lbOf(kg: number): number {
  return Math.round(kg * LB_PER_KG);
}

/** "198 lb (90 kg)": pounds first. */
export function formatWeight(kg: number): string {
  return `${lbOf(kg)} lb (${Math.round(kg)} kg)`;
}

export function weightText(kg: number | undefined): string {
  return kg === undefined ? "" : String(lbOf(kg));
}

/** Kilograms for what was typed in pounds, undefined for empty (the default), null for an unusable entry. */
export function parseWeight(text: string): number | undefined | null {
  const trimmed = text.trim().replace(/\s*(lb|lbs|pounds)$/i, "");
  if (trimmed === "") return undefined;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const kg = Math.round(Number(trimmed) / LB_PER_KG);
  return kg >= SYSTEM_WEIGHT_MIN_KG && kg <= SYSTEM_WEIGHT_MAX_KG ? kg : null;
}

export function weightView(dials: Dials): WeightView {
  const set = dials.systemWeightKg;
  const usual = dials.carrying === "people" ? PASSENGERS_WEIGHT_KG : SYSTEM_WEIGHT_KG;
  const lo = lbOf(SYSTEM_WEIGHT_MIN_KG);
  const hi = lbOf(SYSTEM_WEIGHT_MAX_KG);
  const base =
    "Optional. You, the bike and what it carries, together. A heavier load makes hills count for more when the Hills slider avoids them.";
  return {
    label: WEIGHT_LABEL,
    value: weightText(set),
    min: lo,
    max: hi,
    rule: `Enter ${lo} to ${hi} ${POUNDS_WORD}, or leave it empty.`,
    hint:
      set === undefined
        ? `${base} Left empty, it is ${formatWeight(usual)}.`
        : `${base} Set to ${formatWeight(set)}.`,
  };
}

export const MASS_RIDE_TRAFFIC_NOTE =
  "A mass ride takes the most direct roadway; it is not steered onto side streets.";
/**
 * What the top of the traffic slider does (OWNER-DECISIONS 163, 164): past the
 * old top it stops pricing the router's own roads harder and starts searching
 * for calmer, longer routes, and says so before it plans one.
 */
export function calmNote(stress: number, _preset?: PresetId): string | undefined {
  const rate = calmRate(stress);
  if (rate <= 0) return undefined;
  // The top (OWNER-DECISIONS 256, 257): no rate; the least stressful route within the longest ride.
  if (stress >= STRESS_MAX) {
    return (
      "Calmest: finds the least stressful route within your longest ride, however far round it goes. " +
      "First it avoids heavy-traffic roads (LTS 4) and very high stress junctions. " +
      "Then it avoids busy roads (LTS 3) and higher stress junctions. " +
      "Then it follows the Hills slider. Then it takes the shorter way. " +
      "A quiet street counts the same as a trail. The route summary says how much longer it is."
    );
  }
  // Short sentences (a11y review of integrate-2: one 49-word sentence, which
  // changes at every step and is the slider's description).
  return (
    `Calm detour: up to about ${formatPerMile(rate)} of extra riding for every mile of busy road (LTS 3) avoided. ` +
    "Twice that for a heavy-traffic road (LTS 4). Three times that for a road best avoided. " +
    "The route can be many times the straight-line distance. The route summary says how much longer it is."
  );
}


export const MASS_RIDE_HILLS_NOTE =
  "A mass ride does not look for climbs: at parade pace a climb drops riders below balance speed.";
export const SEEK_NOTE =
  `Looks for climbs among a few alternative routes, up to half again as long; for a start and an end only, up to ${formatRoughDistance(SEEK_MAX_SPAN_M)} apart.`;
export const AVOID_NOTE =
  `Steep grades cost more the steeper they are; long climbs, and on some ride types long steep descents, count most, short kicks little. Weighed among a few alternative routes for a start and an end up to ${formatRoughDistance(AVOID_MAX_SPAN_M)} apart.`;

/**
 * The panel for a ride type, the committed dials, and the position being
 * dragged (`draft`, which is what the words and the warning follow).
 */
export function panelView(preset: PresetId, dials: Dials, draft: Dials = dials): PanelView {
  const locked = stressMax(preset) === 0;
  const seek = hillsMax(preset) > 0;
  // The ride type's start for what the bike carries, at the ride time and
  // with the assist the rider chose: going back resets the sliders only.
  const plain = startDials(preset, dials.carrying, dials.when, dials.assist);
  const start = dials.avoidGravel ? { ...plain, avoidGravel: true } : plain;
  const moved =
    dials.stress !== start.stress ||
    dials.hills !== start.hills ||
    dials.maxDistanceM !== undefined ||
    dials.systemWeightKg !== undefined ||
    dials.loop === true;
  let hillsNote: string | undefined;
  if (!seek) hillsNote = MASS_RIDE_HILLS_NOTE;
  else if (draft.hills > 0) hillsNote = SEEK_NOTE;
  else if (draft.hills < 0) hillsNote = AVOID_NOTE;
  return {
    assistToggle: offersAssist(preset),
    assistNote: offersAssist(preset) && dials.assist,
    traffic: {
      min: STRESS_MIN,
      // A locked slider still spans the whole range, so its thumb sits at the
      // direct end rather than filling the track.
      max: locked ? STRESS_MAX : stressMax(preset),
      words: stressWords(draft.stress),
      ends: ["Traffic tolerant", "Balanced", "Calm at any cost"],
      disabled: locked,
      note: locked ? MASS_RIDE_TRAFFIC_NOTE : calmNote(draft.stress, preset),
    },
    warning: warnsTrafficTolerant(preset, draft.stress) ? TRAFFIC_TOLERANT_WARNING : null,
    hills: {
      min: HILLS_MIN,
      max: hillsMax(preset),
      words: hillsWords(draft.hills),
      ends: seek ? ["Avoid hills", "Fastest", "Seek hills"] : ["Avoid hills", "", "Fastest"],
      disabled: false,
      note: hillsNote,
    },
    longest: offersLongestRide(preset, dials.stress) ? longestView(dials) : null,
    weight: offersLongestRide(preset, dials.stress) ? weightView(dials) : null,
    reset: moved ? start : null,
  };
}

/** The route summary's warning for the dials a route was planned with, or null. */
export function routeWarning(preset: PresetId, dials: { stress: number } | undefined): string | null {
  return dials !== undefined && warnsTrafficTolerant(preset, dials.stress) ? TRAFFIC_TOLERANT_WARNING : null;
}
