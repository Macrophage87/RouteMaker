/**
 * The phone's compass, for a ride's first heading (the owner, 2026-10-26: "Is there a way to determine the initial
 * orientation of a phone for the map?"). GPS gives a heading only once the rider is moving (rideWatch.ts), so a
 * track-up map stood north-up at the start. Until the first GPS heading the map turns to the way the phone faces;
 * that heading then takes over for the rest of the ride (MapView.tsx). No new control: track-up and the ride's
 * compass button decide, as before.
 *
 * Android (Chrome and the app's WebView) gives `deviceorientationabsolute`, needing no permission; iPhones give
 * `webkitCompassHeading` once the rider allows motion and orientation, asked inside the Start ride or Roam press
 * (askCompass). Readings are smoothed, as the compass jumps near metal and cars. Nothing is stored or sent.
 */

/** What an orientation event carries (DeviceOrientationEvent, with iOS's own compass fields). */
export interface CompassEvent {
  absolute?: boolean;
  alpha: number | null;
  beta: number | null;
  gamma: number | null;
  webkitCompassHeading?: number;
  webkitCompassAccuracy?: number;
}

const RAD = Math.PI / 180;

function finite(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function norm(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

/**
 * The way the phone faces, in degrees clockwise from north, or null when the event gives no compass heading.
 * `screenAngle` is the screen's turn (screen.orientation.angle), so a phone held sideways still faces its top.
 *
 * The way it faces is the screen's top for a phone held flat and its back for one held upright (in a handlebar
 * mount), and between the two for one tilted: so the horizontal part of (screen's up + the back), from the W3C
 * rotation (alpha about z, beta about x, gamma about y; https://www.w3.org/TR/orientation-event/).
 */
export function headingOf(event: CompassEvent, screenAngle = 0): number | null {
  if (finite(event.webkitCompassHeading)) {
    // iOS: -1 accuracy is an uncalibrated compass.
    if (finite(event.webkitCompassAccuracy) && event.webkitCompassAccuracy < 0) return null;
    return norm(event.webkitCompassHeading + screenAngle);
  }
  if (event.absolute !== true || !finite(event.alpha)) return null;
  const z = event.alpha * RAD;
  const x = (finite(event.beta) ? event.beta : 0) * RAD;
  const y = (finite(event.gamma) ? event.gamma : 0) * RAD;
  const [cZ, sZ, cX, sX, cY, sY] = [Math.cos(z), Math.sin(z), Math.cos(x), Math.sin(x), Math.cos(y), Math.sin(y)];
  // The device's vector: the screen's up (turned with the screen) plus the back (-z).
  const vx = Math.sin(screenAngle * RAD);
  const vy = Math.cos(screenAngle * RAD);
  const vz = -1;
  const east = (cZ * cY - sZ * sX * sY) * vx - cX * sZ * vy + (cY * sZ * sX + cZ * sY) * vz;
  const north = (cY * sZ + cZ * sX * sY) * vx + cZ * cX * vy + (sZ * sY - cZ * cY * sX) * vz;
  // Pointing straight up or down (held face down past upright): no way ahead to tell.
  if (Math.hypot(east, north) < 0.2) return null;
  return norm(Math.atan2(east, north) / RAD);
}

/** How much a reading moves the smoothed heading (0..1). */
export const COMPASS_SMOOTHING = 0.2;
/** A turn of the smoothed heading smaller than this is not passed on, so the map does not shiver. */
export const COMPASS_STEP_DEG = 4;
/** At most one turn passed on this often. */
export const COMPASS_EVERY_MS = 200;

/** Smooths the compass (as unit vectors, so 359° and 1° average to 0°) and passes on only turns worth showing. */
export class CompassSmoother {
  private x = 0;
  private y = 0;
  private started = false;
  private sent: number | null = null;
  private sentAt = -Infinity;

  /** The heading to show after this reading, or null when the map need not turn. */
  step(deg: number, now: number): number | null {
    const [x, y] = [Math.sin(deg * RAD), Math.cos(deg * RAD)];
    if (this.started) {
      this.x += (x - this.x) * COMPASS_SMOOTHING;
      this.y += (y - this.y) * COMPASS_SMOOTHING;
    } else {
      [this.x, this.y, this.started] = [x, y, true];
    }
    if (Math.hypot(this.x, this.y) < 1e-6) return null;
    const smooth = norm(Math.atan2(this.x, this.y) / RAD);
    if (this.sent !== null) {
      if (now - this.sentAt < COMPASS_EVERY_MS) return null;
      if (Math.abs(norm(smooth - this.sent + 180) - 180) < COMPASS_STEP_DEG) return null;
    }
    this.sent = smooth;
    this.sentAt = now;
    return smooth;
  }
}

/** The browser, behind an interface so tests stub it. */
export interface CompassEnv {
  /** Whether the browser has `deviceorientationabsolute` (Android). */
  hasAbsolute: boolean;
  addEventListener(type: string, listener: (event: CompassEvent) => void): void;
  removeEventListener(type: string, listener: (event: CompassEvent) => void): void;
  screenAngle(): number;
}

export function browserCompassEnv(): CompassEnv | null {
  if (typeof window === "undefined" || typeof window.addEventListener !== "function") return null;
  const target = window as unknown as Pick<CompassEnv, "addEventListener" | "removeEventListener">;
  return {
    hasAbsolute: "ondeviceorientationabsolute" in window,
    addEventListener: (type, listener) => target.addEventListener(type, listener),
    removeEventListener: (type, listener) => target.removeEventListener(type, listener),
    screenAngle: () => {
      const angle = typeof screen !== "undefined" ? screen.orientation?.angle : undefined;
      const legacy = (window as { orientation?: number }).orientation;
      return finite(angle) ? angle : finite(legacy) ? legacy : 0;
    },
  };
}

/** Watch the compass: each smoothed turn worth showing to `onHeading`. Answers the stop function. */
export function watchCompass(env: CompassEnv | null, onHeading: (deg: number) => void, now: () => number = () => Date.now()): () => void {
  if (!env) return () => undefined;
  const type = env.hasAbsolute ? "deviceorientationabsolute" : "deviceorientation";
  const smoother = new CompassSmoother();
  let live = true;
  const listener = (event: CompassEvent) => {
    if (!live) return;
    const deg = headingOf(env.hasAbsolute ? { ...pick(event), absolute: true } : event, env.screenAngle());
    if (deg === null) return;
    const shown = smoother.step(deg, now());
    if (shown !== null) onHeading(shown);
  };
  env.addEventListener(type, listener);
  return () => {
    if (!live) return;
    live = false;
    env.removeEventListener(type, listener);
  };
}

function pick(event: CompassEvent): CompassEvent {
  return { alpha: event.alpha, beta: event.beta, gamma: event.gamma };
}

type AskingOrientation = { requestPermission?: () => Promise<string> };

/**
 * iPhones give the compass only once the rider allows it, asked inside a press: Start ride's and Roam's (no new
 * control). Elsewhere it does nothing. A refusal leaves the map north-up until the rider moves, as before.
 */
export function askCompass(orientation: AskingOrientation | undefined = typeof DeviceOrientationEvent !== "undefined" ? (DeviceOrientationEvent as unknown as AskingOrientation) : undefined): void {
  if (typeof orientation?.requestPermission !== "function") return;
  try {
    void orientation.requestPermission().catch(() => undefined);
  } catch {
    // Not inside a press, or refused outright: north-up until the rider moves.
  }
}
