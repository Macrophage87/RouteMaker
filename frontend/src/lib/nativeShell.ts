/**
 * The phone app (v0.8.0, mobile/): the owner, 2026-10-16, "a standalone app that points to the website
 * would be a nessecity for using it in bikeshare mode as the phone stays in the pocket and navigation
 * cues stop when the phone is off". The app is a thin Capacitor shell that loads this same site; this
 * module is the site's only knowledge of it.
 *
 * In the shell, Capacitor's native bridge puts a `Capacitor` object on the page before the site's own
 * scripts run. Only when that object says it is native (`isNativePlatform()`), Ride mode's three
 * environments are swapped for native ones, through the same interfaces the browser's sit behind:
 *
 * - the position (`RideGeoEnv`, lib/rideWatch.ts): @capacitor-community/background-geolocation, which
 *   keeps fixes coming with the screen locked (an Android foreground service with its "Riding with
 *   RouteMaker" notification; iOS's location background mode). Started by Start ride's watch and
 *   stopped with it (End ride, unmount), exactly as the browser's watch is.
 * - the voice (`SpeechEnv`, lib/rideOutput.ts): @capacitor-community/text-to-speech, which speaks with
 *   the screen locked where Web Speech stops.
 * - the screen wake lock (`WakeEnv`): the browser's lock still asked, but a ride no longer needs the
 *   screen on, so a WebView without the lock is not told "Keep your screen on yourself".
 *
 * On Android a second, silent notification shows the latest cue while a ride's watch runs (`showCue`).
 *
 * In a browser `nativeBridge()` is null and every function here answers the browser's own environment
 * (`browserRideEnv()`, `browserSpeech()`, `browserWake()`), so the site behaves exactly as before. No
 * Capacitor package is imported: the bridge is reached through the global object the shell injects,
 * with its own `nativePromise` and `nativeCallback`, so the web bundle carries none of it.
 *
 * Privacy, as rideWatch.ts: a fix goes to the caller's handler and is forgotten. Nothing here stores,
 * logs or sends a position; the native plugins hand the fix to the page and keep nothing either.
 */
import { browserRideEnv, type RideGeoEnv, type WatchApi, type WatchPosition } from "./rideWatch.ts";
import { browserSpeech, browserWake, toVoice, type CueOutput, type SpeechApi, type SpeechEnv, type UtteranceLike, type WakeEnv, type WakeLockSentinelLike } from "./rideOutput.ts";

/** The parts of the injected `window.Capacitor` used here (Capacitor 8's native-bridge.js). */
export interface CapacitorBridge {
  isNativePlatform(): boolean;
  getPlatform?(): string;
  isPluginAvailable?(name: string): boolean;
  nativePromise(plugin: string, method: string, options?: Record<string, unknown>): Promise<unknown>;
  nativeCallback(plugin: string, method: string, options: Record<string, unknown>, callback: (data: unknown, error?: unknown) => void): string;
}

export const GEO_PLUGIN = "BackgroundGeolocation";
export const SPEECH_PLUGIN = "TextToSpeech";
export const NOTICE_PLUGIN = "LocalNotifications";
/** The app's share sheet (mobile/android/.../SharePlugin.java): Android's WebView has no navigator.share. */
export const SHARE_PLUGIN = "RouteMakerShare";

/** The shell's bridge, or null in a browser (or a page whose `Capacitor` object is not a native one). */
export function nativeBridge(scope: unknown = globalThis): CapacitorBridge | null {
  try {
    const cap = (scope as { Capacitor?: Partial<CapacitorBridge> } | null | undefined)?.Capacitor;
    if (!cap || typeof cap.isNativePlatform !== "function" || cap.isNativePlatform() !== true) return null;
    if (typeof cap.nativePromise !== "function" || typeof cap.nativeCallback !== "function") return null;
    return cap as CapacitorBridge;
  } catch {
    return null;
  }
}

function has(bridge: CapacitorBridge, plugin: string): boolean {
  // Older bridges have no isPluginAvailable: the app ships all three plugins, so assume them.
  try {
    return typeof bridge.isPluginAvailable === "function" ? bridge.isPluginAvailable(plugin) === true : true;
  } catch {
    return false;
  }
}

function platform(bridge: CapacitorBridge): string {
  try {
    return bridge.getPlatform?.() ?? "";
  } catch {
    return "";
  }
}

// ---- The share sheet ------------------------------------------------------------------------------

/**
 * The phone app's share sheet, in navigator.share's shape (lib/share.ts ShareNavigator), or null in a browser or an
 * app built before it had one (Stephen 2026-10-26: "I don't seem to be able to broadcast rides", in the app). The
 * title, text and link only: no files, and no canShare (so Share's GPX file is not offered). Android's chooser does
 * not say whether the rider sent the link or backed out, so an opened sheet counts as sent.
 */
export function nativeShareNavigator(scope: unknown = globalThis): { share: (data: { title: string; text: string; url: string }) => Promise<void> } | null {
  const bridge = nativeBridge(scope);
  if (!bridge || !has(bridge, SHARE_PLUGIN)) return null;
  // An older bridge without isPluginAvailable is not assumed to have it (unlike the three ride plugins, which every
  // build ships): the button would show and then fail.
  if (typeof bridge.isPluginAvailable !== "function") return null;
  return {
    share: ({ title, text, url }) => bridge.nativePromise(SHARE_PLUGIN, "share", { title, text, url }).then(() => undefined),
  };
}

// ---- The latest cue, on Android's notification shade ---------------------------------------------

export const CUE_NOTICE_ID = 8_080;
export const CUE_CHANNEL = "routemaker-ride-cues";
export const CUE_TITLE = "Latest cue";
/**
 * Low importance (2): shown in the shade and on the lock screen, but no sound, no vibration and no
 * heads-up, so an update never talks over the voice. Android sends a screen reader no announcement for
 * a notification below the default importance, so TalkBack does not say each cue a second time.
 */
export const CUE_CHANNEL_SETTINGS = {
  id: CUE_CHANNEL,
  name: "Ride cues",
  description: "The latest cue while a ride is going",
  importance: 2,
  visibility: 1,
  vibration: false,
  lights: false,
} as const;

/**
 * The cue notification: shown and replaced while a ride's watch runs, cleared when the watch stops.
 * One call at a time, in order, so a late update never brings back a notification already cleared.
 */
export class CueNotice {
  private readonly bridge: CapacitorBridge;
  private queue: Promise<void> = Promise.resolve();
  private channelMade = false;
  private refused = false;
  private live = false;
  private last = "";

  constructor(bridge: CapacitorBridge) {
    this.bridge = bridge;
  }

  start(): void {
    this.live = true;
    this.last = "";
  }

  /**
   * The answer to the notifications question asked at Start ride (`askRidePermissions`). Refused: no
   * cue notification this ride, so the plugin's schedule never asks again mid-ride.
   */
  allow(granted: boolean): void {
    this.refused = !granted;
  }

  show(text: string): void {
    if (!this.live || this.refused || !text || text === this.last) return;
    this.last = text;
    this.run(async () => {
      if (!this.live || this.refused) return;
      if (!this.channelMade) {
        await this.bridge.nativePromise(NOTICE_PLUGIN, "createChannel", { ...CUE_CHANNEL_SETTINGS });
        this.channelMade = true;
      }
      if (!this.live) return;
      await this.bridge.nativePromise(NOTICE_PLUGIN, "schedule", {
        notifications: [
          {
            id: CUE_NOTICE_ID,
            title: CUE_TITLE,
            body: text,
            channelId: CUE_CHANNEL,
            ongoing: true,
            autoCancel: false,
            // Shown now: never an alarm, so never Android's "Alarms and reminders" prompt.
            isExactNotification: false,
          },
        ],
      });
    }, true);
  }

  stop(): void {
    if (!this.live) return;
    this.live = false;
    this.last = "";
    this.run(async () => {
      await this.bridge.nativePromise(NOTICE_PLUGIN, "removeDeliveredNotifications", { notifications: [{ id: CUE_NOTICE_ID, title: "", body: "" }] });
      await this.bridge.nativePromise(NOTICE_PLUGIN, "cancel", { notifications: [{ id: CUE_NOTICE_ID }] });
    }, false);
  }

  /** Settled when every call so far has (tests). */
  settled(): Promise<void> {
    return this.queue;
  }

  private run(op: () => Promise<void>, showing: boolean): void {
    this.queue = this.queue.then(op).catch(() => {
      // Notifications refused (Android 13+) or off: the ride goes on without them, and is not asked again.
      if (showing) this.refused = true;
    });
  }
}

// ---- The position -----------------------------------------------------------------------------------

/** What the Android notification of the location service says (the plugin's foreground service). */
export const BACKGROUND_TITLE = "Riding with RouteMaker";
export const BACKGROUND_MESSAGE = "Your location is used for Ride mode's cues and stays on this phone. End the ride to stop.";

/**
 * The plugin's options: the service only while a ride's watch runs; fresh fixes only; every fix. Never
 * the plugin's own permission request: background-geolocation 1.2.26's addWatcher asks for location and
 * starts its foreground service at once, before the answer; Android 14+ refuses a location foreground
 * service without the permission (the plugin swallows the error) and nothing promotes it after the
 * grant, so the first ride would stop at the screen lock. `askRidePermissions` asks first instead.
 */
export const NATIVE_WATCH_OPTIONS = {
  backgroundTitle: BACKGROUND_TITLE,
  backgroundMessage: BACKGROUND_MESSAGE,
  requestPermissions: false,
  stale: false,
  distanceFilter: 0,
} as const;

/** Capacitor's requestPermissions, with the plugins' own aliases (their @Permission annotations). */
export const LOCATION_PERMISSION = { permissions: ["location"] } as const;
export const NOTICE_PERMISSION = { permissions: ["display"] } as const;

export interface RidePermissions {
  location: boolean;
  notices: boolean;
}

/**
 * Asked at Start ride, before the watcher is added: location (Android's "While using the app"), then,
 * on Android, notifications (13+: the "Riding with RouteMaker" service notification and the cue
 * notification need it), so nothing is asked mid-ride at the first cue. Already granted: answered at
 * once, nothing shown. Location refused: notifications are not asked. Rejects only when the location
 * request itself fails.
 */
export async function askRidePermissions(bridge: CapacitorBridge, askNotices: boolean): Promise<RidePermissions> {
  const geo = await bridge.nativePromise(GEO_PLUGIN, "requestPermissions", { permissions: [...LOCATION_PERMISSION.permissions] });
  const location = (geo as { location?: unknown } | null | undefined)?.location === "granted";
  if (!location || !askNotices) return { location, notices: false };
  try {
    const shown = await bridge.nativePromise(NOTICE_PLUGIN, "requestPermissions", { permissions: [...NOTICE_PERMISSION.permissions] });
    return { location, notices: (shown as { display?: unknown } | null | undefined)?.display === "granted" };
  } catch {
    return { location, notices: false };
  }
}

/** The plugin's fix, as its definitions.d.ts gives it. */
interface NativeLocation {
  latitude: number;
  longitude: number;
  accuracy: number;
  speed: number | null;
  bearing: number | null;
  time: number | null;
}

/** The browser's error codes (1 refused, 2 unavailable), which rideWatch.ts already turns into sentences. */
export function nativeErrorCode(error: unknown): number {
  const code = (error as { code?: unknown } | null | undefined)?.code;
  return code === "NOT_AUTHORIZED" ? 1 : 2;
}

export function nativePosition(location: NativeLocation): WatchPosition {
  return {
    coords: { latitude: location.latitude, longitude: location.longitude, accuracy: location.accuracy, speed: location.speed, heading: location.bearing },
    timestamp: location.time ?? undefined,
  };
}

/**
 * A `WatchApi` over the plugin: a watch asks the permissions (`askRidePermissions`), then adds a watcher
 * (the plugin's callback id is its id) and starts the cue notification; clearing it removes the watcher,
 * which stops the service and its notification, and clears the cue notification. A watch cleared while
 * the permission question is still open never adds its watcher.
 */
export function nativeWatchApi(bridge: CapacitorBridge, notice: CueNotice | null, askNotices = notice !== null): WatchApi {
  // null: still asking the permissions; a string: the plugin's callback id.
  const watchers = new Map<number, string | null>();
  let next = 0;
  const drop = (id: number) => {
    watchers.delete(id);
    if (watchers.size === 0) notice?.stop();
  };
  return {
    watchPosition(ok, fail) {
      next += 1;
      const id = next;
      watchers.set(id, null);
      const start = (granted: RidePermissions) => {
        if (!watchers.has(id)) return;
        if (!granted.location) {
          drop(id);
          fail({ code: 1 });
          return;
        }
        let callbackId = "";
        try {
          callbackId = bridge.nativeCallback(GEO_PLUGIN, "addWatcher", { ...NATIVE_WATCH_OPTIONS }, (data, error) => {
            if (watchers.get(id) !== callbackId) return;
            if (error || !data) {
              fail({ code: nativeErrorCode(error) });
              return;
            }
            ok(nativePosition(data as NativeLocation));
          });
        } catch {
          drop(id);
          fail({ code: 2 });
          return;
        }
        watchers.set(id, callbackId);
        if (notice) {
          notice.allow(granted.notices);
          notice.start();
        }
      };
      askRidePermissions(bridge, askNotices).then(start, () => {
        if (!watchers.has(id)) return;
        drop(id);
        fail({ code: 2 });
      });
      return id;
    },
    clearWatch(id) {
      const callbackId = watchers.get(id);
      if (callbackId === undefined) return;
      if (callbackId !== null) void bridge.nativePromise(GEO_PLUGIN, "removeWatcher", { id: callbackId }).catch(() => undefined);
      drop(id);
    },
  };
}

// ---- The voice ----------------------------------------------------------------------------------------

/**
 * A `SpeechEnv` over the plugin, so lib/rideOutput.ts's `Voice` (one utterance at a time; an urgent one
 * cancels) works unchanged. The plugin's speak answers when the sentence ends or is cut off; only the
 * latest utterance's answer counts, so a cancelled one never ends the one that replaced it.
 */
export function nativeSpeech(bridge: CapacitorBridge): SpeechEnv {
  let speaking = false;
  let turn = 0;
  const synth: SpeechApi = {
    get speaking() {
      return speaking;
    },
    speak(utterance: UtteranceLike) {
      turn += 1;
      const mine = turn;
      speaking = true;
      const done = () => {
        if (mine !== turn) return;
        speaking = false;
        utterance.onend?.();
      };
      bridge
        .nativePromise(SPEECH_PLUGIN, "speak", { text: utterance.text, lang: utterance.lang || "en-US", rate: 1, pitch: 1, volume: 1, queueStrategy: 0 })
        .then(done, done);
    },
    cancel() {
      turn += 1;
      speaking = false;
      void bridge.nativePromise(SPEECH_PLUGIN, "stop", {}).catch(() => undefined);
    },
  };
  return { synth, utterance: (text) => ({ text, lang: "", onend: null }) };
}

// ---- The screen wake lock ----------------------------------------------------------------------------

/** Stands for a lock in the shell where the WebView has none: the ride does not need the screen on there. */
function heldWithoutLock(): WakeLockSentinelLike {
  let released = false;
  return {
    get released() {
      return released;
    },
    release: async () => {
      released = true;
    },
  };
}

/** The browser's lock, asked first (it keeps the map lit while the rider looks); never "keep it on yourself". */
export function nativeWake(browser: WakeEnv): WakeEnv {
  const request = browser.request;
  return {
    request: async () => {
      if (request) {
        try {
          return await request();
        } catch {
          // No lock in this WebView, or refused: the native location and voice carry on with it off.
        }
      }
      return heldWithoutLock();
    },
    visible: browser.visible,
  };
}

// ---- What Ride mode asks ------------------------------------------------------------------------------

/** The shell's parts, found once: null in a browser. */
export interface Shell {
  bridge: CapacitorBridge;
  /** Positions come from the native plugin, so they go on with the screen locked. */
  locates: boolean;
  /** The native voice speaks, so cues go on with the screen locked. */
  speaks: boolean;
  notice: CueNotice | null;
}

export function findShell(scope: unknown = globalThis): Shell | null {
  const bridge = nativeBridge(scope);
  if (!bridge) return null;
  const locates = has(bridge, GEO_PLUGIN);
  const speaks = has(bridge, SPEECH_PLUGIN);
  // iOS has no lasting notification: the blue location pill says a ride is on, and a banner per cue
  // would be read by VoiceOver over the voice.
  const notice = locates && platform(bridge) === "android" && has(bridge, NOTICE_PLUGIN) ? new CueNotice(bridge) : null;
  return { bridge, locates, speaks, notice };
}

/**
 * The page's mark that it has this bridge: the app's compatibility layer for older sites
 * (mobile/android/app/src/main/assets/routemaker-compat.js) then leaves the browser APIs alone.
 */
export const BRIDGE_MARK = "__routemakerNativeShell";

/** Mark the page, in the shell only; answers the shell. */
export function markShell(found: Shell | null, scope: unknown = globalThis): Shell | null {
  if (found && scope && typeof scope === "object") (scope as Record<string, unknown>)[BRIDGE_MARK] = true;
  return found;
}

/** Found when this module loads: the bridge is injected before the site's scripts run. */
export const shell: Shell | null = markShell(findShell());

/** Ride mode's position: the native plugin in the shell, else the browser's (rideWatch.ts). */
export function rideGeoEnv(found: Shell | null = shell): RideGeoEnv {
  if (!found?.locates) return browserRideEnv();
  return { isSecureContext: true, geolocation: nativeWatchApi(found.bridge, found.notice) };
}

/** Ride mode's voice: the native one in the shell, else Web Speech. */
export function rideSpeech(found: Shell | null = shell): SpeechEnv {
  return found?.speaks ? nativeSpeech(found.bridge) : browserSpeech();
}

/** Ride mode's screen wake lock: the browser's, and in the shell never a "keep it on yourself". */
export function rideWake(found: Shell | null = shell): WakeEnv {
  return found?.locates ? nativeWake(browserWake()) : browserWake();
}

/** Whether a ride keeps watching while the page is hidden (the screen locked): only with native positions. */
export function ridesHidden(found: Shell | null = shell): boolean {
  return found?.locates === true;
}

/** The latest cue on Android's notification, while a ride's watch runs; nothing elsewhere. */
export function showCue(text: string, found: Shell | null = shell): void {
  found?.notice?.show(text);
}

/**
 * Whether a cue is spoken by the voice: the rider's choice (rideOutput.ts toVoice), as in a browser.
 * One more case in the shell: "My screen reader" with the page hidden (the phone locked, or another app
 * in front). TalkBack and VoiceOver read nothing of a page that is not on screen, so the native voice
 * says the cue then and nothing is said twice; with the page in front again, the screen reader alone.
 * "Neither" stays silent.
 */
export function speaksAloud(output: CueOutput, hidden: boolean, found: Shell | null = shell): boolean {
  if (toVoice(output)) return true;
  return output === "screen-reader" && hidden && found?.speaks === true;
}
