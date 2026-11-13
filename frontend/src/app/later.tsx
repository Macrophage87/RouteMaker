/**
 * The parts of the app a first open does not need (Roam, the review tools, Share live's QR code, the share card,
 * a ride's riders), loaded on first use instead of with App (backlog 2026-11-12, performance 3), and in the
 * background once the page is idle, so the first use seldom waits. Each is still in the service worker's precache
 * (/assets/*, sw/swCore.mjs), so the installed app and offline riding are unchanged.
 *
 * A part whose code does not arrive (offline with no service worker, or a release replaced the files) shows nothing
 * and is asked for again when the connection comes back or the part is next shown: never an error that would take
 * the page, or a ride, down with it.
 */
import { createElement, useEffect, useState, type ComponentType, type ReactNode } from "react";

type Loader = () => Promise<unknown>;
const loaders: Loader[] = [];

/** A component from a module loaded on first render, remembered for the idle preload. */
export function later<P extends object>(load: () => Promise<ComponentType<P>>): ComponentType<P> {
  let loaded: ComponentType<P> | null = null;
  let pending: Promise<ComponentType<P>> | null = null;
  const once = () =>
    (pending ??= load().then(
      (component) => (loaded = component),
      (error: unknown) => {
        pending = null; // the next attempt asks again
        throw error;
      },
    ));
  loaders.push(once);
  function LaterPart(props: P) {
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
      if (loaded) return;
      let live = true;
      const again = () => live && setAttempt((n) => n + 1);
      once().then(again, () => window.addEventListener("online", again, { once: true }));
      return () => {
        live = false;
        window.removeEventListener("online", again);
      };
    }, [attempt]);
    return loaded ? createElement(loaded, props) : null;
  }
  return LaterPart;
}

/** Loads every later part, one after another, when the browser is idle; at most once. */
let preloaded = false;
export function preloadLater(idle: (run: () => void) => void = whenIdle): void {
  if (preloaded) return;
  preloaded = true;
  idle(() => {
    void loaders.reduce<Promise<unknown>>((done, load) => done.then(() => load().catch(() => undefined)), Promise.resolve());
  });
}

function whenIdle(run: () => void): void {
  const w = globalThis as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void };
  if (typeof w.requestIdleCallback === "function") w.requestIdleCallback(run, { timeout: 5_000 });
  else setTimeout(run, 2_000);
}

/** App's hook: the later parts load once the first screen is up. */
export function usePreloadLater(): void {
  useEffect(() => preloadLater(), []);
}

/**
 * Renders `children` (a later part) once `when` has been true, and from then on, so a dialog that closes stays
 * mounted as it did before it was split out.
 */
export function Once({ when, children }: { when: boolean; children: ReactNode }) {
  const [seen, setSeen] = useState(when);
  if (when && !seen) setSeen(true);
  return seen || when ? children : null;
}
