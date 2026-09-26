import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import { MapView, type StressAvailability } from "./MapView.tsx";
import { requestRoute, type RouteError, type RouteResponse } from "./lib/api.ts";
import { MAX_POINTS, addPoint, detour, insideCoverage, type LonLat } from "./lib/geo.ts";
import { formatClimb, formatDistance, formatDuration } from "./lib/format.ts";
import { PRESETS, presetLabel, type PresetId } from "./lib/presets.ts";
import { decodePlan, encodePlan } from "./lib/planHash.ts";
import { stressSegments } from "./lib/stressBar.ts";
import { STRESS_TIERS } from "./stressStyle.js";

type Status = { kind: "idle" } | { kind: "loading" } | { kind: "ok" } | { kind: "error"; error: RouteError };

const initialPlan = decodePlan(window.location.hash);

export function App() {
  const [points, setPoints] = useState<LonLat[]>(initialPlan.points);
  const [preset, setPreset] = useState<PresetId>(initialPlan.preset);
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [routedPoints, setRoutedPoints] = useState<LonLat[]>([]);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [notice, setNotice] = useState<string | null>(null);
  const [stress, setStress] = useState<StressAvailability>("checking");
  const [stressVisible, setStressVisible] = useState(true);
  const [panelOpen, setPanelOpen] = useState(true);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [retryTick, setRetryTick] = useState(0);

  // Keep the link in step with the plan, without adding history entries.
  useEffect(() => {
    window.history.replaceState(null, "", encodePlan(points, preset));
  }, [points, preset]);

  // Route whenever the points or the preset change; a newer request cancels
  // an older one, so a slow answer never overwrites a newer plan.
  useEffect(() => {
    if (points.length < 2) {
      setRoute(null);
      setStatus({ kind: "idle" });
      return;
    }
    const controller = new AbortController();
    setStatus({ kind: "loading" });
    requestRoute(points, preset, { signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setRoute(result.route);
        setRoutedPoints(points);
        setStatus({ kind: "ok" });
      } else if (result.error.kind !== "aborted") {
        setRoute(null);
        setStatus({ kind: "error", error: result.error });
      }
    });
    return () => controller.abort();
  }, [points, preset, retryTick]);

  // The latest points, for handlers the map holds on to between renders.
  const pointsRef = useRef(points);
  pointsRef.current = points;

  const place = useCallback((point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That point is outside the area this map covers (the DC region to Baltimore).");
      return;
    }
    if (pointsRef.current.length >= MAX_POINTS) {
      setNotice(`A route can have at most ${MAX_POINTS} points.`);
      return;
    }
    setNotice(null);
    setPoints((current) => addPoint(current, point));
  }, []);

  const move = useCallback((index: number, point: LonLat) => {
    if (!insideCoverage(point)) {
      setNotice("That point is outside the area this map covers; it was put back.");
      setPoints((current) => [...current]);
      return;
    }
    setNotice(null);
    setPoints((current) => current.map((p, i) => (i === index ? point : p)));
  }, []);

  const removeAt = (index: number) => setPoints((current) => current.filter((_, i) => i !== index));
  const addAtCentre = () => {
    const map = mapRef.current;
    if (!map) return;
    const { lng, lat } = map.getCenter();
    place([lng, lat]);
  };

  const stale = status.kind === "loading";
  const shown = status.kind === "error" ? null : route;

  return (
    <div className="app">
      <MapView
        points={points}
        route={shown}
        stale={stale}
        stressVisible={stressVisible && stress === "available"}
        onStressAvailability={setStress}
        onMapClick={place}
        onMovePoint={move}
        onReady={(map) => {
          mapRef.current = map;
        }}
      />
      <aside className={`panel ${panelOpen ? "open" : "closed"}`} aria-label="Route planner">
        <header className="panel-header">
          <div>
            <h1>RouteMaker</h1>
            <p className="tagline">Bike routes for the DC region and Baltimore. No sign-in needed.</p>
          </div>
          <button
            type="button"
            className="panel-toggle"
            aria-expanded={panelOpen}
            aria-controls="panel-body"
            onClick={() => setPanelOpen((open) => !open)}
          >
            {panelOpen ? "Hide" : "Plan"}
          </button>
        </header>
        <div id="panel-body" className="panel-body" hidden={!panelOpen}>
          <fieldset className="presets">
            <legend>Ride type</legend>
            {PRESETS.map((option) => (
              <label key={option.id} className="preset">
                <input
                  type="radio"
                  name="preset"
                  value={option.id}
                  checked={preset === option.id}
                  onChange={() => setPreset(option.id)}
                />
                <span>
                  <strong>{option.label}</strong>
                  <span className="hint">{option.description}</span>
                </span>
              </label>
            ))}
          </fieldset>

          <section aria-labelledby="points-heading">
            <h2 id="points-heading">Points</h2>
            {points.length === 0 ? (
              <p className="hint">
                Click the map to set a start, then an end. Later clicks add a via point on the
                nearest leg. Drag any marker to move it.
              </p>
            ) : (
              <ol className="points">
                {points.map((point, index) => {
                  const name =
                    index === 0 ? "Start" : index === points.length - 1 && points.length > 1 ? "End" : `Via ${index}`;
                  return (
                    <li key={index}>
                      <span className="point-name">{name}</span>
                      <span className="coords">
                        {point[1].toFixed(4)}, {point[0].toFixed(4)}
                      </span>
                      <button type="button" className="link" onClick={() => removeAt(index)} aria-label={`Remove ${name}`}>
                        Remove
                      </button>
                    </li>
                  );
                })}
              </ol>
            )}
            {points.length === 1 && <p className="hint">Now click the map where you want to finish.</p>}
            <div className="actions">
              <button type="button" onClick={addAtCentre} disabled={points.length >= MAX_POINTS}>
                Add point at map centre
              </button>
              <button type="button" onClick={() => setPoints((p) => [...p].reverse())} disabled={points.length < 2}>
                Reverse
              </button>
              <button type="button" onClick={() => setPoints([])} disabled={points.length === 0}>
                Clear
              </button>
            </div>
            {notice && (
              <p className="notice" role="status">
                {notice}
              </p>
            )}
          </section>

          <section aria-labelledby="route-heading" aria-busy={status.kind === "loading"}>
            <h2 id="route-heading">Route</h2>
            <div role="status" aria-live="polite" className="status-line">
              {status.kind === "loading" && <p className="loading">Planning a {presetLabel(preset)} route…</p>}
              {status.kind === "idle" && points.length < 2 && <p className="hint">No route yet.</p>}
            </div>
            {status.kind === "error" && (
              <div className={`error error-${status.error.kind}`} role="alert">
                <p>
                  <strong>{status.error.title}.</strong> {status.error.message}
                </p>
                {["router-down", "timed-out", "server", "network", "rate-limited"].includes(status.error.kind) && (
                  <button type="button" onClick={() => setRetryTick((n) => n + 1)}>
                    Try again
                  </button>
                )}
              </div>
            )}
            {shown && <RouteSummary route={shown} points={routedPoints} />}
          </section>

          <section aria-labelledby="layers-heading">
            <h2 id="layers-heading">Traffic stress</h2>
            {stress === "available" && (
              <>
                <label className="toggle">
                  <input
                    type="checkbox"
                    checked={stressVisible}
                    onChange={(event) => setStressVisible(event.target.checked)}
                  />
                  Show traffic stress on the map (zoom in to see it)
                </label>
                <StressLegend />
              </>
            )}
            {stress === "checking" && <p className="hint">Checking the stress map…</p>}
            {stress === "unavailable" && (
              <p className="hint">
                Stress map unavailable for now. Routes still show how much of each ride is on each stress level.
              </p>
            )}
          </section>

          <footer className="panel-footer">
            <p>
              <a href="/auth/login">Sign in with Discord</a> to save routes and join peer review. Planning works
              without it, and a plan made signed out is not saved; the link in the address bar reopens it.
            </p>
          </footer>
        </div>
      </aside>
    </div>
  );
}

function RouteSummary({ route, points }: { route: RouteResponse; points: LonLat[] }) {
  const segments = stressSegments(route.stress_m);
  const long = detour(points, route.distance_m);
  return (
    <div className="summary">
      <dl className="stats">
        <div>
          <dt>Distance</dt>
          <dd>{formatDistance(route.distance_m)}</dd>
        </div>
        <div>
          <dt>Time</dt>
          <dd>{formatDuration(route.duration_s)}</dd>
        </div>
        <div>
          <dt>Climb</dt>
          <dd>{formatClimb(route.climb_m)}</dd>
        </div>
        <div>
          <dt>Descent</dt>
          <dd>{formatClimb(route.descent_m)}</dd>
        </div>
      </dl>
      {long.flagged && (
        <p className="notice detour" role="note">
          This route is about {long.ratio.toFixed(1)}× the straight-line distance.
          {route.preset === "mass-ride"
            ? " Mass Ride uses roadways only, so where no roadway crossing is nearby it can go a long way round. Try moving a point, or another ride type."
            : " There may be no direct connection nearby. Try moving a point."}
        </p>
      )}
      {segments.length > 0 && (
        <figure className="stress">
          <figcaption>Traffic stress along the route</figcaption>
          <div className="stress-bar" aria-hidden="true">
            {segments
              .filter((s) => s.fraction > 0)
              .map((s) => (
                <span
                  key={s.key}
                  className={`stress-seg stress-seg-${s.key}`}
                  style={{ width: `${s.fraction * 100}%`, backgroundColor: s.color }}
                  title={`${s.short}: ${s.percent}%`}
                />
              ))}
          </div>
          <ul className="stress-list">
            {segments.map((s) => (
              <li key={s.key}>
                <span className={`swatch stress-seg-${s.key}`} style={{ backgroundColor: s.color }} aria-hidden="true" />
                <span className="stress-name">{s.short}</span>
                <span className="stress-label">{s.label}</span>
                <span className="stress-pct">{s.percent}%</span>
              </li>
            ))}
          </ul>
        </figure>
      )}
      <p className="route-credit">
        Route data: {route.attribution.join("; ")}.
      </p>
    </div>
  );
}

function StressLegend() {
  return (
    <ul className="legend" aria-label="Traffic stress legend">
      {STRESS_TIERS.map((tier) => (
        <li key={tier.tier}>
          <svg width="44" height="10" aria-hidden="true">
            <line
              x1="2"
              y1="5"
              x2="42"
              y2="5"
              stroke={tier.color}
              strokeWidth={tier.width}
              strokeDasharray={tier.dash.map((d: number) => d * tier.width).join(" ")}
            />
          </svg>
          <span className="stress-name">{tier.short}</span>
          <span className="stress-label">{tier.label}</span>
        </li>
      ))}
    </ul>
  );
}
