import { useEffect, useRef, useState } from "react";
import { checkWeather, type WeatherPoint, type WeatherReport } from "./lib/weather.ts";

/**
 * Weather along the route (lib/weather.ts): checked when `key` changes and again every `everyMs` while it stays,
 * from the points `sample` gives at that moment (null: nothing to check, nothing shown). An answer for an older
 * key is dropped; a failed check keeps the last answer for the same key.
 */
export function useWeather(key: string | null, sample: () => { points: WeatherPoint[]; alongM: number[] } | null, everyMs: number): WeatherReport | null {
  const [report, setReport] = useState<{ key: string; report: WeatherReport } | null>(null);
  const sampleRef = useRef(sample);
  sampleRef.current = sample;
  useEffect(() => {
    if (key === null) return;
    let live = true;
    const run = () => {
      const sent = sampleRef.current();
      if (!sent) return;
      void checkWeather(window.location.origin, sent).then((answer) => {
        if (live && answer) setReport({ key, report: answer });
      });
    };
    run();
    const timer = window.setInterval(run, everyMs);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [key, everyMs]);
  return key !== null && report?.key === key ? report.report : null;
}
