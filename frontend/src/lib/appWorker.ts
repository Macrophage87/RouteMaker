/**
 * The page's side of the service worker (WEB-NAV-plan.md section 8, phase P2; the worker itself is
 * src/sw/swCore.mjs): registering it, noticing a new version waiting, and the rider's Reload.
 *
 * - Registered only in a production build, in a secure context, where the browser has workers
 *   (`npm run dev` never registers one: its modules are not the build's).
 * - A new worker that has installed waits. The page says "A new version of RouteMaker is ready" in a
 *   status line with a Reload button (not a dialog, never focus-taking), and never during a ride
 *   (`updateOffered`): the offer comes when the ride ends. Only Reload sends SKIP_WAITING, and the page
 *   reloads itself only after a Reload it asked for (`controllerchange` alone never reloads it).
 * - Checked again when the page comes back to the front, at most once an hour (the browser checks on
 *   every load besides).
 *
 * The environment is passed in (as geolocation.ts's GeoEnv) so the tests drive it with stand-ins.
 */

/** The message the worker skips waiting on (src/sw/swCore.mjs SKIP_WAITING). */
export const SKIP_WAITING = "SKIP_WAITING";
export const WORKER_URL = "/sw.js";
export const CHECK_EVERY_MS = 60 * 60_000;

export const UPDATE_READY = "A new version of RouteMaker is ready.";
export const UPDATE_RELOAD = "Reload";
export const UPDATE_RELOAD_NAME = "Reload RouteMaker to use the new version";
export const OFFLINE_SAID = "You are offline. RouteMaker still opens, and routes you kept for offline open from Settings.";
export const ONLINE_SAID = "Back online.";

/** Whether the update offer shows: a worker waiting, and no ride under way. */
export function updateOffered(ready: boolean, riding: boolean): boolean {
  return ready && !riding;
}

export interface WaitingWorker {
  state?: string;
  postMessage(message: unknown): void;
  addEventListener?(type: "statechange", listener: () => void): void;
}

export interface Registration {
  waiting: WaitingWorker | null;
  installing: WaitingWorker | null;
  update(): Promise<unknown>;
  addEventListener(type: "updatefound", listener: () => void): void;
}

export interface WorkerContainer {
  controller: unknown;
  register(url: string, options: { scope: string; updateViaCache: "none" }): Promise<Registration>;
  addEventListener(type: "controllerchange", listener: () => void): void;
}

export interface WorkerEnv {
  container: WorkerContainer | undefined;
  /** A production build in a secure context. */
  enabled: boolean;
  reload(): void;
  now(): number;
}

export class AppWorker {
  private registration: Registration | null = null;
  private applied = false;
  private reloaded = false;
  private lastCheck = 0;
  private readonly env: WorkerEnv;
  private readonly onReady: (ready: boolean) => void;

  constructor(env: WorkerEnv, onReady: (ready: boolean) => void) {
    this.env = env;
    this.onReady = onReady;
  }

  /** Register the worker; false where there is none to register (dev, insecure, unsupported). */
  async start(): Promise<boolean> {
    const container = this.env.container;
    if (!this.env.enabled || !container) return false;
    container.addEventListener("controllerchange", () => {
      // Only after the rider's Reload: a first install's claim changes the controller too.
      if (this.applied && !this.reloaded) {
        this.reloaded = true;
        this.env.reload();
      }
    });
    try {
      this.registration = await container.register(WORKER_URL, { scope: "/", updateViaCache: "none" });
    } catch {
      return false;
    }
    this.lastCheck = this.env.now();
    const registration = this.registration;
    if (registration.waiting && container.controller) this.onReady(true);
    registration.addEventListener("updatefound", () => {
      const installing = registration.installing;
      installing?.addEventListener?.("statechange", () => {
        // "installed" with a controller is an update waiting; with none, the first install (nothing to offer).
        if (installing.state === "installed" && container.controller) this.onReady(true);
      });
    });
    return true;
  }

  /** The page came back to the front: look for a new version, at most once an hour. */
  check(): void {
    if (!this.registration || this.env.now() - this.lastCheck < CHECK_EVERY_MS) return;
    this.lastCheck = this.env.now();
    void this.registration.update().catch(() => undefined);
  }

  /** The rider pressed Reload. */
  apply(): void {
    const waiting = this.registration?.waiting;
    if (!waiting) {
      // Nothing waiting any more (another tab took it): a plain reload loads the new version.
      this.env.reload();
      return;
    }
    this.applied = true;
    waiting.postMessage({ type: SKIP_WAITING });
  }
}

/** The browser's environment. */
export function browserWorkerEnv(): WorkerEnv {
  const production = import.meta.env.PROD === true;
  const secure = typeof window !== "undefined" && window.isSecureContext;
  const container = typeof navigator !== "undefined" && "serviceWorker" in navigator ? (navigator.serviceWorker as unknown as WorkerContainer) : undefined;
  return {
    container,
    enabled: production && secure,
    reload: () => window.location.reload(),
    now: () => Date.now(),
  };
}
