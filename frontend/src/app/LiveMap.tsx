import type { ComponentProps, ReactNode } from "react";
import { MapView } from "../MapView.tsx";
import type { LonLat } from "../lib/geo.ts";
import { liveValue, useLiveValue, type LiveValue } from "../lib/liveValue.ts";
import type { RideView } from "../RideMode.tsx";

/** The rider on the map in a ride or Roam: a GPS fix, about once a second. */
export type LiveRider = RideView["rider"];

const NO_RIDER: LiveValue<LiveRider> = liveValue<LiveRider>(null);

type MapProps = ComponentProps<typeof MapView>;

/**
 * The map, with the rider's position and the elevation chart's scrub point read from their stores (lib/liveValue.ts):
 * a GPS fix or a scrub re-renders the map alone, not App (fe-perf-1). `riderFrom` is the ride's or Roam's store while
 * on the bike, else null, when the accuracy circle is the located point's (`hereCircle`).
 */
export function LiveMap({
  riderFrom,
  scrubFrom,
  hereCircle,
  ...props
}: Omit<MapProps, "rider" | "accuracy" | "scrubPoint"> & {
  riderFrom: LiveValue<LiveRider> | null;
  scrubFrom: LiveValue<LonLat | null>;
  hereCircle: MapProps["accuracy"];
}) {
  const rider = useLiveValue(riderFrom ?? NO_RIDER);
  const scrubPoint = useLiveValue(scrubFrom);
  const accuracy = riderFrom ? (rider ? { centre: rider.point, radiusM: rider.accuracyM } : null) : hereCircle;
  return <MapView {...props} rider={rider} accuracy={accuracy} scrubPoint={scrubPoint} />;
}

/** `children` given the rider's point now: the ride's, else Roam's, else `fallback` (the ride group's own dot). */
export function LiveRiderPoint({
  ride,
  roam,
  fallback,
  children,
}: {
  ride: LiveValue<LiveRider>;
  roam: LiveValue<LiveRider> | null;
  fallback: LonLat | null;
  children: (point: LonLat | null) => ReactNode;
}) {
  const riding = useLiveValue(ride);
  const roaming = useLiveValue(roam ?? NO_RIDER);
  return children(riding?.point ?? roaming?.point ?? fallback);
}
