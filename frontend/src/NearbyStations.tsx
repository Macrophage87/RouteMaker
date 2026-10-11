/**
 * The nearest stations to take a bike from or return one to (OWNER-DECISIONS 466, 466a).
 *
 * Under the points, once a start (and then an end) is placed: three stations by distance, each a
 * real button named exactly as it is read, "Station name, 82% full, 2 e-bikes, 0.2 mi (320 m)", with
 * aria-pressed for the one chosen. Choosing one makes the plan use it; pressing it again hands the
 * choice back. A list, not a ranking: the rider decides. The list is read from the operator's
 * live feed by the API when a point is placed or moved, and kept nowhere.
 */
import { useEffect, useId, useState } from "react";
import { requestStations } from "./lib/api.ts";
import type { LonLat } from "./lib/geo.ts";
import {
  listPoint,
  stationLabel,
  stationsEmpty,
  stationsFreshness,
  stationsHeading,
  stationsLede,
  type NearbyStation,
  type NearbyStationsAnswer,
  type Pins,
  type StationAction,
} from "./lib/stations.ts";

type State =
  | { kind: "loading" }
  | { kind: "ready"; answer: NearbyStationsAnswer }
  | { kind: "error"; message: string };

function StationList({
  action,
  point,
  chosenId,
  onChoose,
}: {
  action: StationAction;
  point: LonLat;
  chosenId: string | null;
  onChoose: (action: StationAction, station: NearbyStation | null, point: LonLat) => void;
}) {
  const id = useId();
  const [state, setState] = useState<State>({ kind: "loading" });
  const [reload, setReload] = useState(0);
  const lon = point[0];
  const lat = point[1];
  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    requestStations([lon, lat], action, { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      setState(result.ok ? { kind: "ready", answer: result.answer } : { kind: "error", message: result.message });
    });
    return () => controller.abort();
  }, [lon, lat, action, reload]);

  const stations = state.kind === "ready" ? state.answer.stations : [];
  const status =
    state.kind === "loading"
      ? "Looking for nearby stations."
      : state.kind === "error"
        ? state.message
        : stations.length === 0
          ? stationsEmpty(action, state.answer.availability)
          : `${stations.length} nearby ${stations.length === 1 ? "station" : "stations"} listed, nearest first.`;
  return (
    <section className={`nearby-stations nearby-${action}`} aria-labelledby={`${id}-heading`}>
      <h3 id={`${id}-heading`}>{stationsHeading(action)}</h3>
      <p className="hint">{stationsLede(action)}</p>
      <p className="station-status" role="status">
        {status}
      </p>
      {stations.length > 0 && (
        <ul className="station-list" aria-labelledby={`${id}-heading`}>
          {stations.map((station) => {
            const chosen = station.station_id === chosenId;
            return (
              <li key={station.station_id}>
                <button
                  type="button"
                  className={`station-choice${chosen ? " chosen" : ""}`}
                  aria-pressed={chosen}
                  onClick={() => onChoose(action, chosen ? null : station, point)}
                >
                  {stationLabel(station)}
                </button>
                {chosen && (
                  <span className="station-chosen" aria-hidden="true">
                    Chosen
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {chosenId && stations.some((s) => s.station_id === chosenId) && (
        <p className="hint">Press the chosen station again to let the plan choose.</p>
      )}
      {state.kind === "ready" && stations.length > 0 && (
        <p className="hint">{stationsFreshness(state.answer.availability)}</p>
      )}
      {state.kind !== "loading" && (
        <button type="button" className="secondary station-refresh" onClick={() => setReload((n) => n + 1)}>
          {state.kind === "error" ? "Try again" : "Refresh the list"}
        </button>
      )}
    </section>
  );
}

/** The lists for the start (pick-up) and, once there is one, the end (drop-off). */
export function NearbyStations({
  points,
  pins,
  onChoose,
}: {
  points: readonly LonLat[];
  pins: Pins;
  onChoose: (action: StationAction, station: NearbyStation | null, point: LonLat) => void;
}) {
  const pickup = listPoint("pickup", points);
  const dropoff = listPoint("dropoff", points);
  if (!pickup) return null;
  return (
    <div className="nearby-stations-group">
      <StationList
        key={`pickup-${pickup[0]},${pickup[1]}`}
        action="pickup"
        point={pickup}
        chosenId={pins.pickup?.id ?? null}
        onChoose={onChoose}
      />
      {dropoff && (
        <StationList
          key={`dropoff-${dropoff[0]},${dropoff[1]}`}
          action="dropoff"
          point={dropoff}
          chosenId={pins.dropoff?.id ?? null}
          onChoose={onChoose}
        />
      )}
    </div>
  );
}
