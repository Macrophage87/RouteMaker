/**
 * The parts of the app a first open does not need (Roam, the review tools, Share live's QR code, the share card,
 * a ride's riders), loaded on first use instead of with App (backlog 2026-11-12, performance 3), and in the
 * background once the page is idle, so the first use seldom waits. Each is still in the service worker's precache
 * (/assets/*, sw/swCore.mjs), so the installed app and offline riding are unchanged.
 */
import { Suspense, lazy, useEffect, useState, type ComponentType, type ReactNode } from "react";

type Loader = () => Promise<unknown>;
const loaders: Loader[] = [];

/** A component from a module loaded on first render (React.lazy), remembered for the idle preload. */
export function later<P extends object>(load: () => Promise<ComponentType<P>>): ComponentType<P> {
  let pending: Promise<ComponentType<P>> | null = null;
  const once = () => (pending ??= load());
  loaders.push(once);
  return lazy(() => once().then((component) => ({ default: component })));
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
 * mounted as it did before it was split out; nothing shows while its code arrives.
 */
export function Once({ when, children }: { when: boolean; children: ReactNode }) {
  const [seen, setSeen] = useState(when);
  if (when && !seen) setSeen(true);
  return seen || when ? <Suspense fallback={null}>{children}</Suspense> : null;
}

/** A later part shown only while it is rendered (no latch): nothing shows while its code arrives. */
export function Later({ children }: { children: ReactNode }) {
  return <Suspense fallback={null}>{children}</Suspense>;
}
