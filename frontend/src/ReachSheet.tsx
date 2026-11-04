/**
 * Reach (Stephen, 2026-11-04): where the rider can be in 15, 30, 45 and 60 minutes, as rings on Plan's map, from the
 * plan's own points and with its ride type and Ride settings. lib/reach.ts holds the words, the request and the link.
 *
 * Inverted pyramid: the answer in one sentence first, then From/To, how several points combine and Calm streets, then
 * the ride type with a way to its settings, then the rings one by one behind a fold. Share copies a link that opens the
 * same rings.
 */
import { useEffect, useRef, useState } from "react";
import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import { SheetFrame } from "./Sidebar.tsx";
import { Icon } from "./Icon.tsx";
import type { Dials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import { presetLabel, type PresetId } from "./lib/presets.ts";
import { ROUTE_BOTTOM_LAYER } from "./lib/railLayer.ts";
import {
  REACH_CALM_COLOUR,
  REACH_MAX_POINTS,
  areaText,
  placesText,
  reachBody,
  reachFeatures,
  reachNotes,
  reachOffered,
  reachSentence,
  requestReach,
  sharesHome,
  withReach,
  type ReachAnswer,
  type ReachCombine,
  type ReachDirection,
  type ReachView,
} from "./lib/reach.ts";
import { SHEET_TITLES, copyText } from "./lib/sidebar.ts";
import { t } from "./lib/i18n.ts";

const SOURCE = "reach";
const FILL = "reach-fill";
const LINE = "reach-line";
const CALM = "reach-calm";
// Asked again this long after the last change, so a slider drag asks once.
const ASK_AFTER_MS = 500;

const EMPTY = { type: "FeatureCollection", features: [] };

function drawRings(map: MapLibreMap, answer: ReachAnswer | null): void {
  const data = answer ? reachFeatures(answer) : EMPTY;
  const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
  if (source) {
    source.setData(data as never);
    return;
  }
  map.addSource(SOURCE, { type: "geojson", data: data as never });
  const before = map.getLayer(ROUTE_BOTTOM_LAYER) ? ROUTE_BOTTOM_LAYER : undefined;
  // Each ring at a light tint: where they overlap, nearer in, the tint deepens, so the bands read without a legend.
  map.addLayer(
    { id: FILL, type: "fill", source: SOURCE, filter: ["!", ["get", "calm"]], paint: { "fill-color": ["get", "colour"], "fill-opacity": 0.12 } },
    before,
  );
  map.addLayer(
    { id: LINE, type: "line", source: SOURCE, filter: ["!", ["get", "calm"]], paint: { "line-color": ["get", "colour"], "line-width": 1.5, "line-opacity": 0.9 } },
    before,
  );
  map.addLayer(
    { id: CALM, type: "line", source: SOURCE, filter: ["get", "calm"], paint: { "line-color": REACH_CALM_COLOUR, "line-width": 2.5, "line-dasharray": [2, 1.5] } },
    before,
  );
}

function clearRings(map: MapLibreMap): void {
  for (const layer of [CALM, LINE, FILL]) if (map.getLayer(layer)) map.removeLayer(layer);
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
}

function outerBounds(answer: ReachAnswer): [[number, number], [number, number]] | null {
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  const walk = (c: unknown): void => {
    if (Array.isArray(c) && typeof c[0] === "number") {
      west = Math.min(west, c[0] as number);
      east = Math.max(east, c[0] as number);
      south = Math.min(south, c[1] as number);
      north = Math.max(north, c[1] as number);
    } else if (Array.isArray(c)) c.forEach(walk);
  };
  for (const group of answer.groups) walk(group.rings[group.rings.length - 1]?.geometry?.coordinates);
  return Number.isFinite(west) ? [[west, south], [east, north]] : null;
}

interface Props {
  open: boolean;
  onBack: () => void;
  backLabel: string;
  getMap: () => MapLibreMap | null;
  points: readonly LonLat[];
  preset: PresetId;
  dials: Dials;
  runPaceKmh?: number;
  view: ReachView;
  onView: (next: ReachView) => void;
  home: LonLat | null;
  /** Opens the Ride sheet, where the ride type and the traffic slider are. */
  onRideSettings: (opener: HTMLElement) => void;
}

export function ReachSheet({ open, onBack, backLabel, getMap, points, preset, dials, runPaceKmh, view, onView, home, onRideSettings }: Props) {
  const [answer, setAnswer] = useState<ReachAnswer | null>(null);
  const [said, setSaid] = useState("");
  const [busy, setBusy] = useState(false);
  const [shareSaid, setShareSaid] = useState("");
  const fittedFor = useRef("");
  const offered = reachOffered(preset);
  const pointsKey = JSON.stringify(points.slice(0, REACH_MAX_POINTS));
  const bodyKey = offered && points.length ? JSON.stringify(reachBody(points, preset, dials, view, runPaceKmh)) : "";

  // Ask when the sheet is open and anything the rings depend on changes.
  useEffect(() => {
    if (!open) return;
    if (!bodyKey) {
      setAnswer(null);
      setSaid(offered ? t("Put a point on the map (search for a place or tap the map) to see where you can get from it.") : t("The transit ride types have no rings yet. Pick a bike ride type, Walk or Run in Ride settings."));
      return;
    }
    const abort = new AbortController();
    const timer = window.setTimeout(async () => {
      setBusy(true);
      setSaid(t("Drawing the rings…"));
      const result = await requestReach(JSON.parse(bodyKey), undefined, abort.signal);
      if (abort.signal.aborted) return;
      setBusy(false);
      if (result.ok) {
        setAnswer(result.answer);
        setSaid("");
      } else {
        setAnswer(null);
        setSaid(result.message);
      }
    }, ASK_AFTER_MS);
    return () => {
      abort.abort();
      window.clearTimeout(timer);
    };
  }, [open, bodyKey, offered]);

  // The rings on the map while the sheet is open; gone when it closes.
  useEffect(() => {
    const map = getMap();
    if (!map) return;
    if (!open) {
      clearRings(map);
      return;
    }
    drawRings(map, answer);
    if (answer && fittedFor.current !== pointsKey) {
      const bounds = outerBounds(answer);
      // Clear of the panel: beside it on a computer, above Plan's sheet on a phone.
      const narrow = window.innerWidth < 700;
      const padding = { top: 40, right: 40, bottom: narrow ? Math.round(window.innerHeight * 0.5) : 40, left: narrow ? 40 : 440 };
      if (bounds) map.fitBounds(bounds, { padding, maxZoom: 15, duration: 600 });
      fittedFor.current = pointsKey;
    }
  }, [open, answer, getMap, pointsKey]);
  useEffect(() => () => {
    const map = getMap();
    if (map) clearRings(map);
  }, [getMap]);

  const share = async () => {
    const hash = withReach(window.location.hash, view);
    const link = `${window.location.origin}${window.location.pathname}${window.location.search}${hash}`;
    if (navigator.share) {
      try {
        await navigator.share({ title: t("RouteMaker reach"), url: link });
        return;
      } catch {
        // Closed or refused: copied instead.
      }
    }
    const done = await copyText(link, navigator.clipboard, () => false);
    setShareSaid(done ? t("Link copied.") : t("The link could not be copied."));
  };

  const multi = points.length > 1;
  const direction = (d: ReachDirection) => onView({ ...view, direction: d });
  const combine = (c: ReachCombine) => onView({ ...view, combine: c });
  const notes = answer ? reachNotes(answer, dials.stress, points.length) : [];
  const onFoot = preset === "walk" || preset === "run";

  return (
    <SheetFrame id="sheet-reach" title={SHEET_TITLES.reach} open={open} onBack={onBack} backLabel={backLabel}>
      <div className="reach-sheet">
        <p className="reach-answer" role="status" aria-live="polite" aria-busy={busy}>
          {answer && !busy ? reachSentence(answer, points.length) : said}
        </p>
        {notes.map((note) => (
          <p key={note} className="hint">
            {note}
          </p>
        ))}

        <fieldset className="reach-choice">
          <legend>{t("Rings")}</legend>
          <label>
            <input type="radio" name="reach-direction" checked={view.direction === "from"} onChange={() => direction("from")} /> {multi ? t("From the points") : t("From the point")}
          </label>
          <label>
            <input type="radio" name="reach-direction" checked={view.direction === "to"} onChange={() => direction("to")} /> {multi ? t("To the points") : t("To the point")}
          </label>
        </fieldset>

        {multi && (
          <fieldset className="reach-choice">
            <legend>{t("Several points")}</legend>
            <label>
              <input type="radio" name="reach-combine" checked={view.combine === "any"} onChange={() => combine("any")} /> {t("Any of them")}
            </label>
            <label>
              <input type="radio" name="reach-combine" checked={view.combine === "all"} onChange={() => combine("all")} /> {t("All of them")}
            </label>
            <label>
              <input type="radio" name="reach-combine" checked={view.combine === "each"} onChange={() => combine("each")} /> {t("Side by side")}
            </label>
          </fieldset>
        )}

        {!onFoot && (
          <div>
            <label className="reach-calm">
              <input type="checkbox" checked={view.calm} onChange={(e) => onView({ ...view, calm: e.target.checked })} /> {t("Calm streets")}
            </label>
            <p className="hint">{t("Dashed: the same minutes at Low-stress.")}</p>
          </div>
        )}

        <p className="reach-ride">
          {t("{rideType}, with your Ride settings.", { rideType: presetLabel(preset) })}{" "}
          <button type="button" className="link" onClick={(e) => onRideSettings(e.currentTarget)}>
            {t("Change")}
          </button>
        </p>

        {answer && (
          <details className="reach-rings">
            <summary>{t("Ring by ring")}</summary>
            {answer.groups.map((group, g) => (
              <div key={g}>
                {answer.groups.length > 1 && <h3>{t("Point {number}", { number: (group.point ?? g) + 1 })}</h3>}
                <ul>
                  {group.rings.map((ring) => (
                    <li key={ring.minutes}>
                      <strong>{t("{minutes} min", { minutes: ring.minutes })}</strong>: {areaText(ring.area_sq_mi, ring.area_km2)}; {placesText(ring.places)}.
                    </li>
                  ))}
                </ul>
                {group.metro_stations.length > 0 && <p className="hint">{t("Metro: {stations}.", { stations: group.metro_stations.join(", ") })}</p>}
              </div>
            ))}
          </details>
        )}

        <p>
          <button type="button" className="chip" onClick={share} disabled={!answer}>
            <Icon name="link" size={16} />
            {t("Share these rings")}
          </button>
          {sharesHome(points, home) && <span className="hint"> {t("The link shows rings from your Home.")}</span>}
        </p>
        <p className="hint" role="status">
          {shareSaid}
        </p>
      </div>
    </SheetFrame>
  );
}
