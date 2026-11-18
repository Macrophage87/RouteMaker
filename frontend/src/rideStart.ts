/**
 * What App needs from a ride before Ride mode's own code has arrived (foundations, "Ride on first use"): the one voice
 * and its unlock inside the Start press (iOS speaks only after a gesture has), the start and end sentences, and the
 * types App and the map share with RideMode. RideMode.tsx itself loads on first use (src/app/later.tsx), so these live
 * here, where App can import them without pulling the ride screen into the first download.
 */
import type { RouteResponse } from "./lib/api.ts";
import type { RideStopMark } from "./lib/pointKinds.ts";
import type { RideReplans } from "./lib/rideResume.ts";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import type { LetteredPlace } from "./lib/letteredPlaces.ts";
import type { VehicleMark } from "./lib/nextVehicle.ts";
import type { OnBoardPath } from "./lib/onBoard.ts";
import type { planAfterEnd } from "./lib/navigate.ts";
import { Voice, toVoice, type RidePrefs } from "./lib/rideOutput.ts";
import { askCompass } from "./lib/compassHeading.ts";
import { rideSpeech } from "./lib/nativeShell.ts";
import { rideCueLog } from "./lib/cueRecorder.ts";
import { t } from "./lib/i18n.ts";

/**
 * One voice for the page: the Start ride press unlocks it (iOS speaks only after a gesture has). Web
 * Speech in a browser; in the phone app (v0.8.0), the native voice, which goes on with the screen locked.
 */
// What became of each sentence goes to the ride's cue log (lib/cueRecorder.ts): no words or places are kept there.
export const rideVoice = new Voice({ ...rideSpeech(), trace: (what, text) => rideCueLog.voice(what, text, Date.now()) });

/** Said as the ride starts, inside the Start press, so the voice is unlocked by it. */
export const RIDE_STARTED = t("Ride started.");
/** As a walk starts (Walk, Walk + 🚆🚌: its button says "Start walk"). */
export const WALK_STARTED = t("Walk started.");
/** As a run starts (Run, 2026-11-02: its button says "Start run"). */
export const RUN_STARTED = t("Run started.");
/** How long after the start its note (startNote) is said: after "Ride started.". */
export const START_NOTE_MS = 1_500;

/** What End ride leaves behind (lib/navigate.ts planAfterEnd): the plan from here, or as it was. */
export type EndedPlan = ReturnType<typeof planAfterEnd>;
/** The ride as it stood at End ride, after its re-plans (RideMode `onEnd`): what Keep riding carries on with. */
export interface EndedRiding {
  route: RouteResponse;
  points: LonLat[];
  loop: boolean;
  dials: Dials;
  replans: RideReplans;
}
/** Said as the ride ends, by the voice and the page's polite region; the figures are on the summary card. */
export const RIDE_ENDED_SAID = t("Ride ended.");
/** Shown and said with the ride's summary in Plan where End ride came part way (lib/navigate.ts planAfterEnd): the plan now starts where the rider is. */
export const RIDE_ENDED_FROM_HERE_NOTE = t("The route now starts where you are.");
/** Part way in Plan with no recent location: the plan keeps its start, and the rider is told. */
export const RIDE_ENDED_NO_FIX_NOTE = t("Route start unchanged.");

/** Called inside the Start ride press: unlock the voice with the first sentence, where the rider chose it. */
export function startRideGesture(prefs: RidePrefs, walk = false, run = false): void {
  if (toVoice(prefs.output)) rideVoice.unlock(run ? RUN_STARTED : walk ? WALK_STARTED : RIDE_STARTED);
  // iPhones give the compass for the map's first heading only once allowed, asked inside this press (lib/compassHeading.ts).
  askCompass();
}

/** Start's press, before its closure check: unlocks the voice silently (iOS speaks only after a
 * gesture has spoken once), so "Ride started." is said only when the ride does start. */
export function primeRideVoice(prefs: RidePrefs): void {
  if (toVoice(prefs.output)) rideVoice.unlock(" ");
  askCompass();
}

export const VOICE_ON = t("Voice on.");

/** Called inside the press that changes the ride's outputs: a voice newly chosen is unlocked there (iOS). */
export function voiceTurnedOn(before: RidePrefs, next: RidePrefs, voice: Pick<Voice, "unlock"> = rideVoice): void {
  if (!toVoice(before.output) && toVoice(next.output)) voice.unlock(VOICE_ON);
}

/** Said politely when Start's closure check takes more than a moment (CLOSURE_SLOW_MS). */
export const CHECKING_CLOSURES = t("Checking closures…");
export const CLOSURE_SLOW_MS = 600;
/** Said where Start or Resume found Ride mode's code not yet on the phone and it could not be fetched (no service worker
 *  yet, and no signal): the rider stays where they were, never on a ride with no ride screen. */
export const RIDE_NEEDS_SIGNAL = t("The ride needs a connection to start. Try again once you have signal.");

/** What App shows on the map for the ride. */
export interface RideView {
  route: RouteResponse;
  /** The other line (v0.8.2): the standard way through a marked closure, or its detour while on the standard way. */
  other?: LonLat[] | null;
  rider: { point: LonLat; headingDeg: number | null; accuracyM: number } | null;
  /** Where the next train or bus is while the rider waits at a Metro or Metrobus boarding (v0.9.0). */
  vehicle?: VehicleMark | null;
  /** The stops still ahead, drawn on the ride's map with their names (2026-10-24). */
  stops?: RideStopMark[];
  /** The places Detour found, lettered as their rows, while its menu is open or after a row's Show on map (2026-10-28). */
  lettered?: LetteredPlace[] | null;
  /** A lettered pin pressed: Detour opens on its row. */
  onLettered?: (index: number) => void;
  /** The train or bus waited for or ridden past the line, its stops ahead (lib/onBoard.ts onBoardPath). */
  transitPath?: OnBoardPath | null;
  /** Off the route with the way back shown (lib/rejoin.ts wayBackShown): the planned line's nearest point ahead. */
  wayBackTo?: LonLat | null;
}
