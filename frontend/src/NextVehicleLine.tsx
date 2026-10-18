/**
 * Where the next train or bus is, under Ride mode's boarding words while the rider waits there
 * (lib/nextVehicle.ts; v0.9.0). Asks every POLL_MS while mounted, waiting and the page in view, and
 * stops when any of those ends. The line is plain text, not a live region; it is said through
 * `announce` (the ride's polite outputs) only when the count of stations or stops away changes. The
 * map's mark goes to `onMark` (null when there is nothing to show). No answer: nothing at all.
 */
import { useEffect, useRef, useState } from "react";
import type { NextVehicle } from "./lib/api.ts";
import {
  MAX_WAIT_MS,
  MISSES_KEPT,
  POLL_MS,
  boarded,
  requestNextVehicle,
  shouldPoll,
  vehicleMark,
  vehicleSaid,
  vehicleShown,
  type NextVehicleAsk,
  type VehicleMark,
} from "./lib/nextVehicle.ts";

export function NextVehicleLine({
  ask,
  waiting,
  announce,
  onMark,
}: {
  ask: NextVehicleAsk | null;
  /** The rider is at the boarding (the ride to it ended there). */
  waiting: boolean;
  announce?: (text: string) => void;
  onMark?: (mark: VehicleMark | null) => void;
}) {
  const [vehicle, setVehicle] = useState<NextVehicle | null>(null);
  const [hidden, setHidden] = useState(() => typeof document !== "undefined" && document.visibilityState === "hidden");
  const last = useRef<NextVehicle | null>(null);
  const key = ask ? `${ask.system}|${ask.line}|${ask.from.join(",")}|${ask.to.join(",")}` : "";

  useEffect(() => {
    const onVisibility = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  const polling = shouldPoll({ ask, waiting, hidden });
  useEffect(() => {
    if (!polling || !ask) {
      // Not waiting there any more: nothing shown, and the next wait starts afresh.
      last.current = null;
      setVehicle(null);
      onMark?.(null);
      return;
    }
    let live = true;
    let controller: AbortController | null = null;
    let misses = 0;
    const started = Date.now();
    const stop = () => {
      window.clearInterval(timer);
      last.current = null;
      setVehicle(null);
      onMark?.(null);
    };
    const poll = async () => {
      if (Date.now() - started > MAX_WAIT_MS) return stop();
      controller?.abort();
      controller = new AbortController();
      const found = await requestNextVehicle(ask, { signal: controller.signal });
      if (!live) return;
      if (!found) {
        // One or two missed answers keep the last one shown (and the next one compared with it).
        misses += 1;
        if (misses <= MISSES_KEPT && last.current) return;
      } else {
        misses = 0;
      }
      if (boarded(last.current, found)) return stop();
      const said = vehicleSaid(last.current, found);
      last.current = found;
      setVehicle(found);
      onMark?.(vehicleMark(found));
      if (said) announce?.(said);
    };
    const timer = window.setInterval(() => void poll(), POLL_MS);
    void poll();
    return () => {
      live = false;
      window.clearInterval(timer);
      controller?.abort();
      onMark?.(null);
    };
  }, [polling, key]);

  if (!vehicle) return null;
  return <p className="cue-then next-vehicle">{vehicleShown(vehicle)}</p>;
}
