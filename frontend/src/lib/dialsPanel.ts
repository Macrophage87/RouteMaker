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
  milesRange,
  SEEK_MAX_SPAN_M,
  formatDistance,
  formatPerMile,
  formatRoughDistance,
} from "./format.ts";
import type { PresetId } from "./presets.ts";
import { t } from "./i18n.ts";
import {
  HILLS_MIN,
  RIDE_SIZE_DEFAULT,
  RIDE_SIZE_MAX,
  RIDE_SIZE_MIN,
  RIDE_SIZE_STEP,
  offersRideSize,
  rideSizeOf,
  DEFAULT_CEILING_RATIO,
  NOVICE_CEILING_RATIO,
  TARGET_CEILING_RATIO,
  TARGET_MAX_M,
  TARGET_MIN_M,
  STRESS_MAX,
  STRESS_MIN,
  TRAFFIC_TOLERANT_WARNING,
  calmRate,
  hillsMax,
  hillsWords,
  seeksClimbs,
  offersAssist,
  offersTargetDistance,
  startDials,
  trailsAreOff,
  trailsOffLocked,
  stressMax,
  stressWords,
  warnsTrafficTolerant,
  type Dials,
  worthRatio,
  LT1_GRADE_MAX_PCT,
  LT1_GRADE_MIN_PCT,
  hillsAtGrade,
  hillsGradePosition,
} from "./dials.ts";

export interface SliderView {
  min: number;
  max: number;
  /** The slider's step; absent is 5. */
  step?: number;
  /**
   * Where the slider shows another scale than the dial's own: the dial's value on the slider,
   * and back. The Hills slider shows grade percent (Stephen, 2026-10-23: "Can the slider
   * positions just be percent?").
   */
  scale?: { toSlider: (value: number) => number; fromSlider: (position: number) => number };
  words: string;
  ends: [string, string, string];
  disabled: boolean;
  /** Its description, under it: kept short (DESCRIPTION_MAX_CHARS) where it can be. */
  note?: string;
  /**
   * The note in full, where the line shown is its short form (P10): read as the slider's description and shown
   * behind the row's (i), so nothing is lost by the shorter line.
   */
  noteSaid?: string;
  /** The detail, under a "How this works" disclosure, not read on every step. */
  how?: string;
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
  /** Mass Ride's "Anticipated ride size" (PLAN items 128, 129, 139), or null on any other ride type. */
  rideSize: SliderView | null;
  /** The "Target distance" number input, or null where the traffic slider is not at the top. */
  target: TargetView | null;
  /** The "Keep to roads, not trails" switch (OWNER-DECISIONS 463, 463b), on every ride type. */
  trailsOff: TrailsOffView;
  /** Where "Back to this ride type's settings" goes, or null when already there. */
  reset: Dials | null;
}

/** The "Target distance" dial (OWNER-DECISIONS 256, 271), in miles first, kilometres in brackets. */
export interface TargetView {
  label: string;
  /** What the input holds, in miles to a tenth; empty is the default. */
  value: string;
  min: number;
  max: number;
  /** The rule for an entry the planner will not take, as words (not a colour). */
  rule: string;
  /** Under the input, and its description: what it does, and what is set (short). */
  hint: string;
  /** The detail, under a "How this works" disclosure: not read on every focus. */
  how?: string;
}

/** The "Keep to roads, not trails" switch: on and unchangeable on Mass Ride, the rider's on any other ride type. */
export interface TrailsOffView {
  label: string;
  checked: boolean;
  /** Always on (Mass Ride): the switch stays in the Tab order, but a press changes nothing. */
  locked: boolean;
  /** Its description, read on focus: short, in plain words. */
  hint: string;
  /** What exactly is left out, under "How this works": read when opened. */
  how: string;
  /** Read after "How this works", not shown, to tell its disclosure from the other dials' ones. */
  howAbout: string;
}

/** OWNER-DECISIONS 463b: checked is roads only. The link and API keep `trailsoff` / `trails_off`. */
export const TRAILS_OFF_LABEL = t("Keep to roads, not trails");
/**
 * What "trails" means, as the no-trail graph builds it (`pipeline.variants.inject`,
 * `TRAIL_CLASS_HIGHWAY`): every way tagged cycleway, footway, path, pedestrian,
 * bridleway or steps is left out, whatever its bicycle tag, plus the roadways of
 * bridges that are ridden by their side path (Chain Bridge, the George Mason span,
 * the Wilson Bridge). What stays is every street and road bikes may use.
 */
export const TRAILS_OFF_HINT = t("No bike paths, trails or stairs. Can use the Key and Memorial Bridge roadways.");
export const TRAILS_OFF_LOCKED_HINT = `${t("A mass ride always keeps to roads.")} ${TRAILS_OFF_HINT}`;
export const TRAILS_OFF_HOW_ABOUT = t("keep to roads");
export const TRAILS_OFF_HOW =
  t("Leaves out every separate bike path, trail, sidewalk or footway, boardwalk, pedestrian street, bridle path and set of stairs, however it is signed for bikes. Bridges whose bike route is a side path, such as Chain Bridge, are left out. Unpaved farm and forest roads stay. Bike lanes painted on a road stay, with no extra credit for them. Never rides against a one-way street's traffic. Where roads alone cannot join your points, there is no route.");

export const TARGET_LABEL = t("Target distance (miles)");

/** The input's text for a length in metres: miles to a tenth, no trailing ".0"; empty for none. */
export function targetText(metres: number | undefined): string {
  if (metres === undefined) return "";
  const miles = Math.round((metres / METRES_PER_MILE) * 10) / 10;
  return String(miles);
}

/** Metres for what was typed in miles, or undefined for empty (the default); null where it is not a usable entry. */
export function parseTarget(text: string): number | undefined | null {
  const trimmed = text.trim().replace(/\s*(mi|miles)$/i, "");
  if (trimmed === "") return undefined;
  if (!/^\d+(\.\d+)?$/.test(trimmed)) return null;
  const metres = Math.round(Number(trimmed) * METRES_PER_MILE);
  return metres >= TARGET_MIN_M && metres <= TARGET_MAX_M ? metres : null;
}

const TARGET_MIN_MILES = Math.ceil((TARGET_MIN_M / METRES_PER_MILE) * 10) / 10;
const TARGET_MAX_MILES = Math.floor(TARGET_MAX_M / METRES_PER_MILE);

/** A description is read on every focus, so it is kept under this many characters (the a11y review's N1). */
export const DESCRIPTION_MAX_CHARS = 150;

export function targetView(dials: Dials): TargetView {
  const set = dials.targetDistanceM;
  // One short sentence or two as the description; the ordering detail is under
  // "How this works" (`how`), read only when opened.
  const hint =
    set === undefined
      ? t("Optional: the calmest route at or under this. Left empty, it may be up to {ratio} times the usual route.", { ratio: DEFAULT_CEILING_RATIO })
      : t("Optional: the calmest route at or under this. Set to {distance}; never past {limit}.", { distance: formatDistance(set), limit: formatDistance(set * TARGET_CEILING_RATIO) });
  return {
    label: TARGET_LABEL,
    value: targetText(set),
    min: TARGET_MIN_MILES,
    max: TARGET_MAX_MILES,
    rule: t("Enter {range}, or leave it empty.", { range: milesRange(TARGET_MIN_MILES, TARGET_MAX_MILES, TARGET_MIN_M, TARGET_MAX_M) }),
    hint,
    how: TARGET_HOW,
  };
}

/** The target's "How this works" (OWNER-DECISIONS 258-262, 267, 271, 287(2), 287(3), 435). */
export const TARGET_HOW =
  t("The route is as calm as it can be: the fewest heavy-traffic roads and very high stress junctions first, then busy roads and higher stress junctions, then distance. Up to your target, each extra mile must still avoid a tenth of a mile of busy road. It goes past your target only where the extra miles avoid enough busy road, and never past {ratio} times it. If the calmest route is longer than your target, it is still the one chosen, and the route summary says how far over your target it is.", { ratio: TARGET_CEILING_RATIO });

export const MASS_RIDE_TRAFFIC_NOTE =
  t("A mass ride takes the most direct roadway; it is not steered onto side streets.");
/**
 * What the top of the traffic slider does (OWNER-DECISIONS 163, 164): past the
 * old top it stops pricing the router's own roads harder and starts searching
 * for calmer, longer routes, and says so before it plans one.
 */
export function calmNote(stress: number, _preset?: PresetId): string | undefined {
  // What the score's rate accepts, capped by the worth bar every longer route must meet
  // (OWNER-DECISIONS 435, "One rule": `worthRatio`).
  const rate = Math.min(calmRate(stress), worthRatio(stress));
  if (calmRate(stress) <= 0) return undefined;
  // The top (OWNER-DECISIONS 256, 257, 271): no rate; the least stressful route towards
  // the target distance, within its ceiling (1.25 times the target, or 1.6 times the
  // usual route with none). The order it weighs things in is CALM_HOW, under "How
  // this works": this is the slider's description, read at every step (the a11y review's N1).
  if (stress >= STRESS_MAX) {
    return t("Calmest: finds the least stressful route towards your target distance, within a set limit. The route summary says how much longer it is.");
  }
  // Short sentences (a11y review of integrate-2: one 49-word sentence, which
  // changes at every step and is the slider's description).
  return t("Calm detour: up to about {rate} of extra riding for every mile of busy road (LTS 3) avoided. Twice that for a heavy-traffic road (LTS 4). Three times that for a road best avoided. The route can be many times the straight-line distance. The route summary says how much longer it is.", { rate: formatPerMile(rate) });
}

/**
 * The note's line as shown (P10): one short line under the slider. The full sentence (`calmNote`) is read as the
 * slider's description and shown behind its (i).
 */
export function calmNoteShort(stress: number, preset?: PresetId): string | undefined {
  const full = calmNote(stress, preset);
  if (full === undefined || stress >= STRESS_MAX) return full;
  const rate = Math.min(calmRate(stress), worthRatio(stress));
  return t("Calm detour: up to {rate} extra per busy mile avoided.", { rate: formatPerMile(rate) });
}

/** The top of the traffic slider's (i): the order it weighs things in. */
export const CALM_HOW =
  t("First it avoids heavy-traffic roads (LTS 4) and very high stress junctions. Then it avoids busy roads (LTS 3) and higher stress junctions. Then it follows the Hills slider. Then it takes the shorter way. A quiet street counts the same as a trail, except on Trailmaxxing and Cargo with passengers, where low-stress streets (LTS 2) count a little extra. Novice and Nervous treats every road as one step busier and goes no further than {novice} times the usual route. Otherwise it goes no further than {target} times your target distance, or {usual} times the usual route when no target is set.", { novice: NOVICE_CEILING_RATIO, target: TARGET_CEILING_RATIO, usual: DEFAULT_CEILING_RATIO });

export const MASS_RIDE_HILLS_NOTE =
  t("A mass ride does not look for climbs: at parade pace a climb drops riders below balance speed.");
export const SEEK_NOTE =
  t("Looks for climbs among a few alternative routes, up to half again as long; for a start and an end only, up to {span} apart.", { span: formatRoughDistance(SEEK_MAX_SPAN_M) });
/** At the top of the traffic slider seeking climbs only breaks ties (OWNER-DECISIONS 298(3)). */
export const SEEK_CALM_NOTE =
  t("At this Traffic setting, looking for climbs only chooses between equally calm routes, preferring the one that climbs more.");
/** "Fine with hills", the right half on every ride type but Mountain Goat (FOLLOWUP-HILLS-TOLERATE, OWNER-DECISIONS 242). */
export const TOLERATE_NOTE =
  t("Climbs up to this grade cost only the time they take, so a shorter route over a hill wins where it is quicker, but never a busier one. Compared for a start and an end up to {span} apart.", { span: formatRoughDistance(AVOID_MAX_SPAN_M) });
/** At the top of the traffic slider the stress order decides; its distance counts each climb's time. */
export const TOLERATE_CALM_NOTE =
  t("At this Traffic setting the calmest route decides; climbing counts as the time it takes.");
export const AVOID_NOTE =
  t("Climbs cost the time they take, and grades past this one cost more the steeper and longer they are, as do long steep descents on some ride types. Weighed among a few alternative routes for a start and an end up to {span} apart.", { span: formatRoughDistance(AVOID_MAX_SPAN_M) });
/** Each hills note's one line as shown (P10); the note in full is read and is behind the row's (i). */
export const HILLS_NOTE_SHORT: ReadonlyMap<string, string> = new Map([
  [SEEK_NOTE, t("Looks for climbs, on routes up to half again as long.")],
  [SEEK_CALM_NOTE, t("Climbs only choose between equally calm routes.")],
  [TOLERATE_NOTE, t("Climbs up to this grade cost only their time.")],
  [TOLERATE_CALM_NOTE, t("Calmest route decides; climbs cost their time.")],
  [AVOID_NOTE, t("Grades past this one cost extra.")],
]);
/**
 * The Hills slider's help (Stephen, 2026-10-23): "have the rider estimate the steepest they can climb for several
 * minutes without any labored breating using their lowest gears. If they are metric people then say upper end of
 * Zone 2 Power (75% FTP)", "And just leave as is and adjust if not sure", and "Just make it clear that while we're
 * using an FTP model, were just basing it on a comfortable climb grade". The slider sets that grade
 * (`routemaker.hill_cost.lt1_grade_for`).
 */
export const HILLS_HOW =
  t("Set this to the steepest grade you can climb for several minutes in your lowest gears without labored breathing. Not sure? Leave it where it starts and adjust after a ride or two; a rough guess plans much the same routes. Every climb counts as the time it takes. Past this grade it counts for more when choosing a route, more again the harder it gets, and having to push the bike counts as a last resort. (With a power meter: the grade you climb at the top of Zone 2, 75% of FTP. That is only the curve's shape; you set nothing but the grade.)");

/**
 * The panel for a ride type, the committed dials, and the position being
 * dragged (`draft`, which is what the words and the warning follow).
 */
export function panelView(preset: PresetId, dials: Dials, draft: Dials = dials): PanelView {
  const locked = stressMax(preset) === 0;
  const seek = hillsMax(preset) > 0;
  const climbs = seeksClimbs(preset);
  // The ride type's start for what the bike carries, at the ride time and
  // with the assist the rider chose: going back resets the sliders only.
  const plain = startDials(preset, dials.carrying, dials.when, dials.assist, dials.bike ?? null);
  // A Mass Ride hides Make it a loop and keeps it for the next ride type
  // (OWNER-DECISIONS 374): there it is no moved setting, and Reset keeps it.
  const hiddenLoop = preset === "mass-ride" && dials.loop === true;
  const start = {
    ...plain,
    ...(dials.avoidGravel ? { avoidGravel: true } : {}),
    ...(dials.trailsOff ? { trailsOff: true } : {}),
    ...(hiddenLoop ? { loop: true } : {}),
  };
  const moved =
    dials.stress !== start.stress ||
    dials.hills !== start.hills ||
    dials.targetDistanceM !== undefined ||
    (dials.loop === true && !hiddenLoop) ||
    (offersRideSize(preset) && rideSizeOf(dials) !== RIDE_SIZE_DEFAULT);
  let hillsNote: string | undefined;
  if (!seek) hillsNote = MASS_RIDE_HILLS_NOTE;
  else if (draft.hills > 0 && climbs) hillsNote = draft.stress >= STRESS_MAX ? SEEK_CALM_NOTE : SEEK_NOTE;
  else if (draft.hills > 0) hillsNote = draft.stress >= STRESS_MAX ? TOLERATE_CALM_NOTE : TOLERATE_NOTE;
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
      ends: [t("Traffic tolerant"), t("Balanced"), t("Calm at any cost")],
      disabled: locked,
      ...shortNote(locked ? MASS_RIDE_TRAFFIC_NOTE : calmNote(draft.stress, preset), locked ? undefined : calmNoteShort(draft.stress, preset)),
      ...(!locked && draft.stress >= STRESS_MAX ? { how: CALM_HOW } : {}),
    },
    warning: warnsTrafficTolerant(preset, draft.stress) ? TRAFFIC_TOLERANT_WARNING : null,
    hills: climbs
      ? {
          min: HILLS_MIN,
          max: hillsMax(preset),
          words: hillsWords(draft.hills, climbs),
          ends: [t("Avoid hills"), t("Fastest"), t("Seek hills")],
          disabled: false,
          ...shortNote(hillsNote, hillsNote && HILLS_NOTE_SHORT.get(hillsNote)),
          how: HILLS_HOW,
        }
      : {
          min: LT1_GRADE_MIN_PCT,
          max: hillsGradePosition(hillsMax(preset)),
          step: 1,
          scale: { toSlider: hillsGradePosition, fromSlider: hillsAtGrade },
          words: hillsWords(draft.hills, climbs),
          ends: seek
            ? [`${LT1_GRADE_MIN_PCT}%`, `${hillsGradePosition(0)}%`, `${LT1_GRADE_MAX_PCT}%`]
            : [`${LT1_GRADE_MIN_PCT}%`, "", `${hillsGradePosition(0)}%`],
          disabled: false,
          ...shortNote(hillsNote, hillsNote && HILLS_NOTE_SHORT.get(hillsNote)),
          how: HILLS_HOW,
        },
    rideSize: offersRideSize(preset) ? rideSizeView(rideSizeOf(draft)) : null,
    target: offersTargetDistance(preset, dials.stress) ? targetView(dials) : null,
    trailsOff: {
      label: TRAILS_OFF_LABEL,
      checked: trailsAreOff(preset, dials),
      locked: trailsOffLocked(preset),
      hint: trailsOffLocked(preset) ? TRAILS_OFF_LOCKED_HINT : TRAILS_OFF_HINT,
      how: TRAILS_OFF_HOW,
      howAbout: TRAILS_OFF_HOW_ABOUT,
    },
    reset: moved ? start : null,
  };
}

/** The ride size slider's name: its unit is in it, so it is said with the number (riders). */
export const RIDE_SIZE_LABEL = t("Anticipated ride size (riders)");
export const RIDE_SIZE_NOTE =
  t("How many riders you expect. It sets the group's length, which the corker load counts over. It does not change the route.");
/** Its line as shown (P10); RIDE_SIZE_NOTE is read, and is behind the row's (i). */
export const RIDE_SIZE_NOTE_SHORT = t("Sets group length; route unchanged.");

/** A note and its shown short form: `noteSaid` only where the two differ. */
function shortNote(note: string | undefined, shown: string | undefined): { note?: string; noteSaid?: string } {
  if (note === undefined) return {};
  return shown && shown !== note ? { note: shown, noteSaid: note } : { note };
}

/** "500 riders", as the slider's value text and the words beside its name. */
export function rideSizeWords(riders: number): string {
  return t("{count} riders", { count: riders.toLocaleString("en-US") });
}

export function rideSizeView(riders: number): SliderView {
  return {
    min: RIDE_SIZE_MIN,
    max: RIDE_SIZE_MAX,
    step: RIDE_SIZE_STEP,
    words: rideSizeWords(riders),
    ends: [RIDE_SIZE_MIN.toLocaleString("en-US"), "", RIDE_SIZE_MAX.toLocaleString("en-US")],
    disabled: false,
    ...shortNote(RIDE_SIZE_NOTE, RIDE_SIZE_NOTE_SHORT),
  };
}

/** The route summary's warning for the dials a route was planned with, or null. */
export function routeWarning(preset: PresetId, dials: { stress: number } | undefined): string | null {
  return dials !== undefined && warnsTrafficTolerant(preset, dials.stress) ? TRAFFIC_TOLERANT_WARNING : null;
}
