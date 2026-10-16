// Small hooks the planner shell (App.tsx) uses, moved out of it unchanged (UI-CLEANUP step 4: App.tsx split
// into the planner, route panel and sheet modules with no change in behaviour).
import { useEffect, useRef, useState } from "react";
import { SettledText } from "../lib/settle.ts";

/** The phone layout's media query: below it the panel is a bottom sheet (styles.css). */
export const NARROW = "(max-width: 720px)";

/** Whether the phone layout (the bottom sheet) is showing, kept up to date. */
export function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(() => window.matchMedia(NARROW).matches);
  useEffect(() => {
    const query = window.matchMedia(NARROW);
    const onChange = () => setNarrow(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

/** Whether `on` has been true for `afterMs` without a break: false again at once when it goes false. */
export function useLongerThan(on: boolean, afterMs: number): boolean {
  const [long, setLong] = useState(false);
  useEffect(() => {
    if (!on) {
      setLong(false);
      return;
    }
    const timer = window.setTimeout(() => setLong(true), afterMs);
    return () => window.clearTimeout(timer);
  }, [on, afterMs]);
  return on && long;
}

/** `text` once it has stood for `waitMs`; "" at once (lib/settle.ts SettledText). */
export function useSettled(text: string, waitMs: number): string {
  const [shown, setShown] = useState("");
  const settled = useRef<SettledText | null>(null);
  if (settled.current === null) settled.current = new SettledText(waitMs, setShown);
  useEffect(() => settled.current?.offer(text), [text]);
  useEffect(() => () => settled.current?.cancel(), []);
  return shown;
}

/** The time now, epoch ms, read again each minute while `on` (the light times on the route, lib/lightTimes.ts). */
export function useMinute(on: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, [on]);
  return now;
}
