import { useEffect, useRef, useState } from "react";
import { checkWeather, type WeatherPoint, type WeatherReport } from "./lib/weather.ts";
import { TICK_MS, onSharedTick } from "./lib/sharedTick.ts";

/**
 * Weather along the route (lib/weather.ts): checked when `key` changes and again every `everyMs` while it stays,
 * from the points `sample` gives at that moment (null: nothing to check, nothing shown). An answer for an older
 * key is dropped; a failed check keeps the last answer for the same key.
 *
 * The checks after the first go on the page's shared 5-minute boundaries (lib/sharedTick.ts), with the closures and
 * rail checks, so the radio wakes once for all (the owner, 2026-11-01: battery audit); `everyMs` of 10 minutes checks
 * at every other boundary. Hidden, nothing is checked unless `whileHidden` (the app's ride, whose weather warnings are
 * spoken with the screen locked); a check missed while hidden runs as the page is in front again.
 */
export function useWeather(
  key: string | null,
  sample: () => { points: WeatherPoint[]; alongM: number[] } | null,
  everyMs: number,
  whileHidden = false,
): WeatherReport | null {
  const [report, setReport] = useState<{ key: string; report: WeatherReport } | null>(null);
  const sampleRef = useRef(sample);
  sampleRef.current = sample;
  useEffect(() => {
    if (key === null) return;
    let live = true;
    let ranAt = 0;
    const run = () => {
      const sent = sampleRef.current();
      if (!sent) return;
      ranAt = Date.now();
      void checkWeather(window.location.origin, sent).then((answer) => {
        if (live && answer) setReport({ key, report: answer });
      });
    };
    run();
    const off = onSharedTick(
      () => {
        // A boundary sooner than `everyMs` after the last check is skipped (a minute's slack for the boundaries).
        if (Date.now() - ranAt >= everyMs - 60_000 || everyMs <= TICK_MS) run();
      },
      { whileHidden: () => whileHidden, catchUp: true },
    );
    return () => {
      live = false;
      off();
    };
  }, [key, everyMs, whileHidden]);
  return key !== null && report?.key === key ? report.report : null;
}
