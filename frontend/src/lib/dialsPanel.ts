/**
 * What the dials panel and the route summary show, decided here rather than
 * in the components so it is tested without a browser (the lane has no DOM
 * harness; mutation review r1, UI1-UI5: hiding the traffic-tolerant warning,
 * unlocking Mass Ride's traffic slider or letting its hills slider seek all
 * went unnoticed while the decisions lived in DialsPanel.tsx and
 * FacilityBreakdown.tsx).
 */
import { AVOID_MAX_SPAN_M, SEEK_MAX_SPAN_M, formatPerMile, formatRoughDistance } from "./format.ts";
import type { PresetId } from "./presets.ts";
import {
  HILLS_MIN,
  STRESS_MAX,
  STRESS_MIN,
  TRAFFIC_TOLERANT_WARNING,
  calmRate,
  hillsMax,
  hillsWords,
  offersAssist,
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
  /** Where "Back to this ride type's settings" goes, or null when already there. */
  reset: Dials | null;
}

export const MASS_RIDE_TRAFFIC_NOTE =
  "A mass ride takes the most direct roadway; it is not steered onto side streets.";
/**
 * What the top of the traffic slider does (OWNER-DECISIONS 163, 164): past the
 * old top it stops pricing the router's own roads harder and starts searching
 * for calmer, longer routes, and says so before it plans one.
 */
export function calmNote(stress: number): string | undefined {
  const rate = calmRate(stress);
  if (rate <= 0) return undefined;
  return (
    `Calm detour: up to about ${formatPerMile(rate)} of extra riding for every mile of busy road (LTS 3) ` +
    "avoided, twice that for a heavy-traffic road (LTS 4) and three times for a road best avoided. " +
    "The route can be many times the straight line, and says how much longer it is."
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
  const moved = dials.stress !== start.stress || dials.hills !== start.hills;
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
      note: locked ? MASS_RIDE_TRAFFIC_NOTE : calmNote(draft.stress),
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
    reset: moved ? start : null,
  };
}

/** The route summary's warning for the dials a route was planned with, or null. */
export function routeWarning(preset: PresetId, dials: { stress: number } | undefined): string | null {
  return dials !== undefined && warnsTrafficTolerant(preset, dials.stress) ? TRAFFIC_TOLERANT_WARNING : null;
}
