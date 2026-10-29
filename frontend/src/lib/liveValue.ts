import { useSyncExternalStore } from "react";

/**
 * A value that changes often (the rider's GPS fix about once a second, the elevation chart's scrub point on every
 * pointer move) kept outside React state, so that only the components that draw it re-render when it changes: App
 * sets it, the map reads it with useLiveValue (fe-perf-1). Setting the same value again notifies no one.
 */
export interface LiveValue<T> {
  get: () => T;
  set: (value: T) => void;
  subscribe: (listener: () => void) => () => void;
}

export function liveValue<T>(initial: T): LiveValue<T> {
  let value = initial;
  const listeners = new Set<() => void>();
  return {
    get: () => value,
    set: (next) => {
      if (Object.is(next, value)) return;
      value = next;
      for (const listener of [...listeners]) listener();
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}

/** The live value now, re-rendering the calling component when it changes. */
export function useLiveValue<T>(live: LiveValue<T>): T {
  return useSyncExternalStore(live.subscribe, live.get, live.get);
}
