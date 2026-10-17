/**
 * Review mode (lib/review.ts; the owner, 2026-10-16: "Basically we'd have 3 modes for people who have admin access
 * go/plan/review"), beside Go and Plan for an instance admin.
 *
 * Desktop first, a split view: the panel holds every list with its count (a nav of toggle buttons), the chosen
 * list as a table with sortable columns, and the chosen road's card (its levels, every rating it holds side by side,
 * the facts behind them, its street photo and its history) with the ruling buttons; the map beside it zooms to the
 * road. The riders' suggestions, Mass Ride hazard reports and closure reports keep their own reviews
 * (SuggestionReview.tsx, ClosureReview.tsx), hosted here.
 *
 * The map (the owner, 2026-10-16 15:39 UTC: "Make sure that discrepancies can be easily found in the map. Generally
 * highlighted, with those roads viewable from a distance"): every road of every list, not just a page, drawn bold with
 * a light halo above the stress lines, a colour and a dash pattern a list (lib/review.ts QUEUE_STYLE, colour-blind
 * safe), with a dot a road below a street's zoom so a short one never vanishes; zoomed further out, nearby roads are
 * one badge with their count, which zooms in when chosen (a road alone keeps its line, so no badge lies over its own
 * roads). One switch a list shows or hides its roads, and Next discrepancy (Alt+Shift+N, left to a text box) goes to
 * the next road with no ruling, in the lists' order (GET /api/review/next). The map asks for its view alone once it
 * settles (GET /api/review/map: the view's roads at its zoom, up to a cap, simplified below a street's zoom), never a
 * list's whole map.
 *
 * Keyboard and screen readers: every control is a real button, select, checkbox or text box with a name; in the
 * table, Up and Down move between the roads' buttons, and choosing one moves the focus to its card's heading, where
 * Up and Down go on to the road before or after it in the list's order (a road opened from the map included); the
 * card has Previous road and Next road. Every result is said in the app's polite live region, messages said
 * together joined rather than one overwriting another (makeAnnouncer), and the progress line ("12 of 601 reviewed")
 * follows every ruling. Levels are said in words as well as numbers; lengths in miles first, kilometres after. The
 * card asks for a road's facts and photo once a held arrow key settles (SETTLE_MS).
 *
 * A ruling informed by an agency whose public use is still pending is the admin's own: its level is shown as
 * information only (the admin picks a level with the usual control), and the private reason is never filled in
 * from that row.
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { SuggestionReview } from "./SuggestionReview.tsx";
import { ClosureReview } from "./ClosureReview.tsx";
import { StreetPhotoView } from "./StreetPhotoView.tsx";
import { useMap } from "./app/mapOverlay.ts";
import { CLIMB_FONT } from "./lib/climbs.ts";
import { HAZARD_REVIEW } from "./lib/reviewSources.ts";
import { csrfFromCookie } from "./lib/stressEditor.ts";
import { STREET_VIEW_NOTE, STREET_VIEW_TEXT } from "./lib/roadInfo.ts";
import {
  DEFAULT_LIST,
  LISTS,
  NO_FILTERS,
  QUEUES,
  QUEUE_STYLE,
  REVIEW_STEPS,
  SETTLE_MS,
  decisionLabel,
  drawnOf,
  fetchMapView,
  fetchNext,
  fetchQueues,
  fetchRoadDetail,
  fetchRoads,
  isQueue,
  makeAnnouncer,
  piecesText,
  progressText,
  roadHeading,
  roadRowLabel,
  roadStreetViewUrl,
  ruledSaid,
  rulingLabel,
  sendRuling,
  sortRoads,
  stepText,
  trafficText,
  typingIn,
  undoRuling,
  viewBox,
  type Decision,
  type Fact,
  type Filters,
  type ListKey,
  type QueueKey,
  type MapView,
  type QueueSummary,
  type ReviewRoad,
  type RoadDetail,
  type Ruling,
  type SortKey,
  type Spot,
} from "./lib/review.ts";

const CURRENT = "review-current";
const CURRENT_HALO = "review-current-halo";
const LINES = "review-lines";
const HALO = "review-halo";
const BADGES = "review-badges";
const BADGE_COUNT = "review-badge-count";
const DOTS = "review-dots";
const lineLayer = (queue: QueueKey) => `review-line-${queue}`;
/** Up to here the server groups nearby roads into a badge with their count (core.stress_review.CLUSTER_ZOOM). */
const BADGE_MAX_ZOOM = 10;
/** How long the map is still before its view is asked for. */
const VIEW_WAIT_MS = 300;
const NEXT_KEYS = "Alt+Shift+N";
const EMPTY = { type: "FeatureCollection", features: [] };
const PHOTO_PATH = "/api/review/street-photo";

export interface ReviewModeProps {
  getMap: () => MapLibreMap | null;
  announce: (text: string) => void;
  /** A stress change was made: the map asks for its tiles again. */
  onStressChanged: (generation: number) => void;
  onHazardsChanged: () => void;
  /** The list to open on (Suggest's Review button opens the riders' suggestions). */
  list?: ListKey;
  onList?: (list: ListKey) => void;
}

export function ReviewMode({ getMap, announce, onStressChanged, onHazardsChanged, list: wanted, onList }: ReviewModeProps) {
  const base = useId();
  const [list, setList] = useState<ListKey>(wanted ?? DEFAULT_LIST);
  const [queues, setQueues] = useState<QueueSummary[] | null>(null);
  const [problem, setProblem] = useState("");
  const [onMap, setOnMap] = useState<Set<QueueKey>>(() => new Set(QUEUES));
  // The view's roads as last answered, and the lists they were asked for.
  const [view, setView] = useState<{ view: MapView; lists: QueueKey[] } | null>(null);
  // Bumped when the map settles after a move, and when a ruling or an undo changes what it shows.
  const [moved, setMoved] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [spot, setSpot] = useState<Spot | null>(null);
  const [asked, setAsked] = useState<{ spot: Spot; n: number } | null>(null);
  const origin = window.location.origin;
  const say = useMemo(() => makeAnnouncer(announce), [announce]);

  useEffect(() => {
    if (wanted) setList(wanted);
  }, [wanted]);

  const loadQueues = useCallback(async () => {
    const found = await fetchQueues(origin);
    if (typeof found === "string") setProblem(found);
    else {
      setProblem("");
      setQueues(found);
    }
  }, [origin]);

  useEffect(() => {
    void loadQueues();
  }, [loadQueues]);

  const summary = (key: ListKey) => queues?.find((q) => q.queue === key) ?? null;
  const labelOf = (key: ListKey) => LISTS.find((l) => l.key === key)?.label ?? "";
  // The lists drawn: switched on, with roads.
  const drawnLists = QUEUES.filter((q) => onMap.has(q) && (summary(q)?.total ?? 0) > 0);
  const drawnKey = drawnLists.join(",");
  const computedKey = (queues ?? []).map((q) => `${q.queue}:${q.computed_at ?? ""}`).join(",");

  // The view's roads, asked for once the map settles: never a list's whole map.
  useEffect(() => {
    const lists = drawnKey ? (drawnKey.split(",") as QueueKey[]) : [];
    // A request a newer view replaces is cancelled.
    const controller = new AbortController();
    const wait = window.setTimeout(() => {
      const map = getMap();
      if (!map) return;
      if (lists.length === 0) {
        setView(null);
        return;
      }
      const b = map.getBounds();
      const zoom = map.getZoom();
      void fetchMapView(origin, lists, viewBox(b.getWest(), b.getSouth(), b.getEast(), b.getNorth(), zoom), zoom, fetch, controller.signal).then((found) => {
        if (!controller.signal.aborted && typeof found !== "string") setView({ view: found, lists });
      });
    }, VIEW_WAIT_MS);
    return () => {
      controller.abort();
      window.clearTimeout(wait);
    };
  }, [moved, refresh, drawnKey, computedKey, origin, getMap]);

  const choose = (key: ListKey) => {
    setList(key);
    onList?.(key);
    setAsked(null);
    const s = isQueue(key) ? summary(key) : null;
    say(s ? `${labelOf(key)}: ${progressText(s.reviewed, s.total)}.` : `${labelOf(key)}.`);
  };

  // A road to open: tapped on the map, or Next discrepancy. In another list, that list opens on it.
  const open = useCallback(
    (to: Spot) => {
      if (to.queue !== list) {
        setList(to.queue);
        onList?.(to.queue);
      }
      setAsked((old) => ({ spot: to, n: (old?.n ?? 0) + 1 }));
    },
    [list, onList],
  );
  const openRef = useRef(open);
  openRef.current = open;

  // The next road with no ruling, in the lists' order: after the one open, then each following list drawn, then round.
  // Only the newest press opens its answer: a slower earlier one never opens after it.
  const nextAsked = useRef(0);
  const goNext = useCallback(async () => {
    const asking = ++nextAsked.current;
    const lists = drawnKey ? (drawnKey.split(",") as QueueKey[]) : [];
    if (lists.length === 0) {
      say("No more roads without a ruling on the map.");
      return;
    }
    const from: Spot | null = spot ?? (isQueue(list) ? { queue: list, way: -1 } : null);
    const next = await fetchNext(origin, { lists, queue: from?.queue ?? lists[0], way: from && from.way >= 0 ? from.way : null });
    if (asking !== nextAsked.current) return;
    if (typeof next === "string") {
      say(next);
      return;
    }
    if (!next) {
      say("No more roads without a ruling on the map.");
      return;
    }
    if (next.queue !== (isQueue(list) ? list : null)) say(`${labelOf(next.queue)}.`);
    open(next);
    // labelOf reads LISTS only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spot, list, drawnKey, origin, say, open]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.altKey && event.shiftKey && !event.ctrlKey && !event.metaKey && event.code === "KeyN") {
        // A letter typed into a text box is the box's.
        if (typingIn(event.target)) return;
        event.preventDefault();
        void goNext();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [goNext]);

  // The map: the view's roads, bold with a halo above the stress lines, a dot a road, and the far view's count badges.
  useMap(
    getMap,
    (map) => {
      for (const source of [LINES, DOTS, BADGES]) if (!map.getSource(source)) map.addSource(source, { type: "geojson", data: EMPTY as never });
      // Under the chosen road's highlight where it is already drawn; otherwise on top of everything.
      const before = map.getLayer(CURRENT_HALO) ? CURRENT_HALO : undefined;
      const width = ["interpolate", ["linear"], ["zoom"], 5, 3, 12, 5, 16, 8];
      if (!map.getLayer(HALO))
        map.addLayer(
          {
            id: HALO,
            type: "line",
            source: LINES,
            layout: { "line-cap": "round", "line-join": "round" },
            paint: { "line-color": "#ffffff", "line-opacity": 0.9, "line-width": ["interpolate", ["linear"], ["zoom"], 5, 6, 12, 9, 16, 13] },
          } as never,
          before,
        );
      for (const queue of QUEUES) {
        const style = QUEUE_STYLE[queue];
        if (map.getLayer(lineLayer(queue))) continue;
        map.addLayer(
          {
            id: lineLayer(queue),
            type: "line",
            source: LINES,
            filter: ["==", ["get", "queue"], queue],
            layout: { "line-cap": style.dash ? "butt" : "round", "line-join": "round" },
            paint: {
              "line-color": style.colour,
              "line-width": width,
              // A road with a standing ruling fades.
              "line-opacity": ["case", ["get", "ruled"], 0.35, 1],
              ...(style.dash ? { "line-dasharray": style.dash } : {}),
            },
          } as never,
          before,
        );
      }
      if (!map.getLayer(DOTS))
        map.addLayer(
          {
            id: DOTS,
            type: "circle",
            source: DOTS,
            paint: {
              "circle-color": ["match", ["get", "queue"], ...QUEUES.flatMap((q) => [q, QUEUE_STYLE[q].colour]), "#000000"],
              "circle-opacity": ["case", ["get", "ruled"], 0.35, 1],
              "circle-radius": 5,
              "circle-stroke-color": "#ffffff",
              "circle-stroke-width": 2,
            },
          } as never,
          before,
        );
      if (!map.getLayer(BADGES))
        map.addLayer(
          {
            id: BADGES,
            type: "circle",
            source: BADGES,
            paint: {
              "circle-color": "#1f2937",
              "circle-radius": ["step", ["get", "count"], 13, 10, 16, 100, 20, 1000, 24],
              "circle-stroke-color": "#ffffff",
              "circle-stroke-width": 2,
            },
          } as never,
          before,
        );
      if (!map.getLayer(BADGE_COUNT))
        map.addLayer(
          {
            id: BADGE_COUNT,
            type: "symbol",
            source: BADGES,
            layout: {
              "text-field": ["case", [">=", ["get", "count"], 1000], ["concat", ["to-string", ["/", ["round", ["/", ["get", "count"], 100]], 10]], "k"], ["to-string", ["get", "count"]]],
              "text-font": [CLIMB_FONT],
              "text-size": 12,
              "text-allow-overlap": true,
            },
            paint: { "text-color": "#ffffff" },
          } as never,
          before,
        );
      const tapped = [...QUEUES.map(lineLayer), DOTS];
      const onRoad = (event: MapMouseEvent & { features?: Array<{ properties?: Record<string, unknown> }> }) => {
        const props = event.features?.[0]?.properties;
        const way = Number(props?.way);
        const queue = props?.queue as QueueKey | undefined;
        if (Number.isFinite(way) && queue && QUEUES.includes(queue)) openRef.current({ queue, way });
      };
      // A badge zooms in to where its roads are drawn.
      const onBadge = (event: MapMouseEvent) => map.easeTo({ center: event.lngLat, zoom: Math.min(map.getZoom() + 2, BADGE_MAX_ZOOM + 0.5) });
      const enter = () => (map.getCanvas().style.cursor = "pointer");
      const leave = () => (map.getCanvas().style.cursor = "");
      const onMove = () => setMoved((n) => n + 1);
      for (const layer of [...tapped, BADGES]) {
        map.on("mouseenter", layer, enter);
        map.on("mouseleave", layer, leave);
      }
      for (const layer of tapped) map.on("click", layer, onRoad);
      map.on("click", BADGES, onBadge);
      map.on("moveend", onMove);
      onMove();
      return () => {
        for (const layer of [...tapped, BADGES]) {
          map.off("mouseenter", layer, enter);
          map.off("mouseleave", layer, leave);
        }
        for (const layer of tapped) map.off("click", layer, onRoad);
        map.off("click", BADGES, onBadge);
        map.off("moveend", onMove);
        for (const layer of [BADGE_COUNT, BADGES, DOTS, ...QUEUES.map(lineLayer), HALO]) if (map.getLayer(layer)) map.removeLayer(layer);
        for (const source of [BADGES, DOTS, LINES]) if (map.getSource(source)) map.removeSource(source);
      };
    },
    [],
  );

  // What the map shows: the view's roads of the lists switched on now (one switched off goes at once).
  const shownView = useMemo(() => drawnOf(view?.view ?? null, view?.lists ?? [], drawnKey ? (drawnKey.split(",") as QueueKey[]) : []), [view, drawnKey]);
  useMap(
    getMap,
    (map) => {
      (map.getSource(LINES) as GeoJSONSource | undefined)?.setData((shownView?.lines ?? EMPTY) as never);
      (map.getSource(DOTS) as GeoJSONSource | undefined)?.setData((shownView?.dots ?? EMPTY) as never);
      (map.getSource(BADGES) as GeoJSONSource | undefined)?.setData((shownView?.badges ?? EMPTY) as never);
    },
    [shownView],
  );

  const toggle = (queue: QueueKey, on: boolean) => {
    const next = new Set(onMap);
    if (on) next.add(queue);
    else next.delete(queue);
    setOnMap(next);
    say(`${labelOf(queue)} ${on ? "shown" : "hidden"} on the map.`);
  };

  const mapped = QUEUES.filter((q) => (summary(q)?.total ?? 0) > 0);

  return (
    <section className="review-mode" aria-labelledby={`${base}-heading`}>
      <h2 id={`${base}-heading`}>Review</h2>
      {problem && <p role="alert">{problem}</p>}
      <div className="review-layout">
        <div className="review-side">
          <nav className="review-lists" aria-label="Review lists">
            <ul>
              {LISTS.map((l) => {
                const s = isQueue(l.key) ? summary(l.key) : null;
                return (
                  <li key={l.key}>
                    <button type="button" className="review-list-button" aria-pressed={list === l.key} onClick={() => choose(l.key)}>
                      <span className="review-list-name">{l.label}</span>
                      {s && <span className="review-list-count">{s.wired ? progressText(s.reviewed, s.total) : s.note || "Not wired yet"}</span>}
                    </button>
                  </li>
                );
              })}
            </ul>
          </nav>
          <fieldset className="review-map-lists">
            <legend>On the map</legend>
            {mapped.length === 0 && <p className="hint">No list has roads to draw yet.</p>}
            {mapped.map((queue) => {
              const style = QUEUE_STYLE[queue];
              return (
                <label key={queue} className="review-map-toggle">
                  <input type="checkbox" checked={onMap.has(queue)} onChange={(event) => toggle(queue, event.target.checked)} />
                  <svg className="review-swatch" width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">
                    <line x1="2" y1="5" x2="26" y2="5" stroke="#ffffff" strokeWidth="8" strokeLinecap="round" />
                    <line x1="2" y1="5" x2="26" y2="5" stroke={style.colour} strokeWidth="4" strokeDasharray={style.dash ? style.dash.map((d) => d * 4).join(" ") : undefined} />
                  </svg>
                  {labelOf(queue)} ({style.colourName}, {style.pattern}): {(summary(queue)?.total ?? 0).toLocaleString("en-US")}
                </label>
              );
            })}
            <button type="button" className="secondary review-next" aria-keyshortcuts={NEXT_KEYS} onClick={goNext}>
              Next discrepancy <span className="hint">({NEXT_KEYS})</span>
            </button>
            {view?.view.truncated && <p className="hint">Only the largest roads in view are drawn: zoom in for the rest.</p>}
          </fieldset>
        </div>
        <div className="review-main">
          {isQueue(list) ? (
            <QueueView
              key={list}
              queue={list}
              summary={summary(list)}
              label={labelOf(list)}
              getMap={getMap}
              say={say}
              asked={asked && asked.spot.queue === list ? { way: asked.spot.way, n: asked.n } : null}
              onCurrent={(way) => setSpot(way === null ? null : { queue: list, way })}
              onStressChanged={onStressChanged}
              onRuled={() => {
                setRefresh((n) => n + 1);
                void loadQueues();
              }}
              onUndone={() => {
                setRefresh((n) => n + 1);
                void loadQueues();
              }}
            />
          ) : list === "suggestions" ? (
            <SuggestionReview onStressChanged={onStressChanged} />
          ) : list === "hazards" ? (
            <SuggestionReview source={HAZARD_REVIEW} onApproved={onHazardsChanged} />
          ) : (
            <ClosureReview />
          )}
        </div>
      </div>
    </section>
  );
}

const COLUMNS: Record<"rebuild" | "disagreement" | "other", { key: SortKey | null; label: string }[]> = {
  rebuild: [
    { key: "name", label: "Road" },
    { key: "area", label: "Area" },
    { key: "old", label: "Before" },
    { key: "new", label: "After" },
    { key: null, label: "Decided by" },
    { key: "traffic", label: "Traffic" },
    { key: "length", label: "Length" },
    { key: null, label: "Ruling" },
  ],
  disagreement: [
    { key: "name", label: "Road" },
    { key: "area", label: "Area" },
    { key: "new", label: "Now" },
    { key: null, label: "Ratings" },
    { key: "spread", label: "Spread" },
    { key: "traffic", label: "Traffic" },
    { key: "length", label: "Length" },
    { key: null, label: "Ruling" },
  ],
  other: [
    { key: "name", label: "Road" },
    { key: "area", label: "Area" },
    { key: "new", label: "Now" },
    { key: null, label: "Reason" },
    { key: "length", label: "Length" },
    { key: null, label: "Ruling" },
  ],
};

/** The map's facts and the new build's side by side, a row a fact (a rebuild's change); the map's alone elsewhere. */
function factRows(now: Fact[], next: Fact[]): { label: string; now: string; next: string }[] {
  const words = (facts: Fact[], label: string) =>
    facts
      .filter((f) => f.label === label)
      .map((f) => `${f.value}${f.source ? ` (${f.source})` : ""}`)
      .join("; ");
  const labels = [...new Set([...now.map((f) => f.label), ...next.map((f) => f.label)])];
  return labels.map((label) => ({ label, now: words(now, label), next: words(next, label) }));
}

interface QueueViewProps {
  queue: QueueKey;
  label: string;
  summary: QueueSummary | null;
  getMap: () => MapLibreMap | null;
  say: (text: string) => void;
  /** A road to open (a tap on the map, or Next discrepancy). */
  asked: { way: number; n: number } | null;
  onCurrent: (way: number | null) => void;
  onStressChanged: (generation: number) => void;
  onRuled: () => void;
  onUndone: () => void;
}

function QueueView({ queue, label, summary, getMap, say, asked, onCurrent, onStressChanged, onRuled, onUndone }: QueueViewProps) {
  const base = useId();
  const id = (part: string) => `${base}-${part}`;
  const origin = window.location.origin;
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [all, setAll] = useState(false);
  const [page, setPage] = useState(1);
  const [roads, setRoads] = useState<ReviewRoad[] | null>(null);
  const [total, setTotal] = useState(0);
  const [problem, setProblem] = useState("");
  const [sort, setSort] = useState<{ key: SortKey; ascending: boolean }>({ key: "score", ascending: false });
  const [current, setCurrent] = useState<ReviewRoad | null>(null);
  // The road the card has settled on: a held arrow key asks for no facts, photo or zoom until it stops.
  const [settled, setSettled] = useState<ReviewRoad | null>(null);
  const [detail, setDetail] = useState<RoadDetail | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [step, setStep] = useState(3);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<Ruling | null>(null);
  const [said, setSaid] = useState("");
  const [focusNext, setFocusNext] = useState<string | null>(null);
  // A road asked for from the map: the page's own first road does not replace it when the page arrives.
  const opening = useRef<number | null>(null);
  const perPage = 50;
  const columns = COLUMNS[queue === "rebuild" ? "rebuild" : queue === "disagreement" ? "disagreement" : "other"];
  const tell = (text: string) => {
    setSaid(text);
    say(text);
  };

  const load = useCallback(
    async (number: number, keep: number | null = null) => {
      const found = await fetchRoads(origin, queue, filters, { page: number, perPage, all });
      if (typeof found === "string") {
        setProblem(found);
        return null;
      }
      setProblem("");
      setRoads(found.items);
      setTotal(found.total);
      setPage(found.page);
      setSelected(new Set());
      if (opening.current === null) {
        const next = (keep !== null && found.items.find((r) => r.osm_way_id === keep)) || found.items[0] || null;
        setCurrent(next);
      }
      return found;
    },
    [origin, queue, filters, all],
  );

  useEffect(() => {
    void load(1);
  }, [load]);

  useEffect(() => {
    onCurrent(current?.osm_way_id ?? null);
    const wait = window.setTimeout(() => setSettled(current), SETTLE_MS);
    return () => window.clearTimeout(wait);
    // onCurrent is the parent's setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, roads, current]);

  // The settled road's facts and history.
  useEffect(() => {
    setDetail(null);
    if (!settled) return;
    let live = true;
    void fetchRoadDetail(origin, settled.osm_way_id, queue === "rebuild" ? "rebuild" : null).then((found) => {
      if (live && typeof found !== "string") setDetail(found);
    });
    return () => {
      live = false;
    };
  }, [origin, settled, queue]);

  // The chosen road, highlighted at once and zoomed to once settled.
  useMap(
    getMap,
    (map) => {
      if (!map.getSource(CURRENT)) map.addSource(CURRENT, { type: "geojson", data: EMPTY as never });
      if (!map.getLayer(CURRENT_HALO))
        map.addLayer({ id: CURRENT_HALO, type: "line", source: CURRENT, layout: { "line-cap": "round" }, paint: { "line-width": 16, "line-color": "#ffffff", "line-opacity": 0.95 } });
      if (!map.getLayer(CURRENT))
        map.addLayer({ id: CURRENT, type: "line", source: CURRENT, layout: { "line-cap": "round" }, paint: { "line-width": 9, "line-color": "#000000", "line-opacity": 0.9 } });
      return () => {
        for (const layer of [CURRENT, CURRENT_HALO]) if (map.getLayer(layer)) map.removeLayer(layer);
        if (map.getSource(CURRENT)) map.removeSource(CURRENT);
      };
    },
    [],
  );
  useMap(
    getMap,
    (map) => {
      (map.getSource(CURRENT) as GeoJSONSource | undefined)?.setData((current?.geometry ? { type: "Feature", geometry: current.geometry, properties: {} } : EMPTY) as never);
    },
    [current],
  );
  useMap(
    getMap,
    (map) => {
      if (!settled?.bbox) return;
      const [w, s, e, n] = settled.bbox;
      const panel = document.getElementById("route-planner")?.getBoundingClientRect();
      const left = panel && panel.right < window.innerWidth * 0.8 ? panel.right + 24 : 40;
      map.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        { padding: { left, right: 40, top: 60, bottom: 60 }, maxZoom: 17, duration: 400 },
      );
    },
    [settled],
  );

  // A road asked for from the map or Next discrepancy: its card, with the list as it is.
  const openWay = useCallback(
    async (way: number) => {
      opening.current = way;
      const found = await fetchRoads(origin, queue, NO_FILTERS, { all: true, way });
      if (opening.current === way) opening.current = null;
      if (typeof found === "string" || found.items.length === 0) return;
      const road = found.items[0];
      setCurrent(road);
      tell(`${roadHeading(road)}.`);
      setFocusNext(id("card"));
    },
    // tell and id are stable in effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [origin, queue],
  );
  useEffect(() => {
    if (asked) void openWay(asked.way);
  }, [asked?.n, asked?.way, openWay]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = roads ? sortRoads(roads, sort.key, sort.ascending) : [];
  const index = current ? shown.findIndex((r) => r.osm_way_id === current.osm_way_id) : -1;
  const pick = (road: ReviewRoad, focusCard = true) => {
    setCurrent(road);
    if (focusCard) setFocusNext(id("card"));
  };
  const besideAsked = useRef(0);
  const move = (by: number) => {
    if (index >= 0) {
      const next = shown[index + by];
      if (next) pick(next);
      else tell(by > 0 ? "That is the last road on this page." : "That is the first road on this page.");
      return;
    }
    // A road opened from the map, off this page: the road beside it in the list's order (the server's); only the newest
    // press's answer opens.
    if (!current) return;
    const asking = ++besideAsked.current;
    void fetchNext(origin, { lists: [queue], queue, way: current.osm_way_id, direction: by > 0 ? 1 : -1, openOnly: !all, wrap: false }).then((beside) => {
      if (asking !== besideAsked.current) return;
      if (typeof beside === "string") tell(beside);
      else if (beside) void openWay(beside.way);
      else tell(by > 0 ? "That is the last road in this list." : "That is the first road in this list.");
    });
  };

  const rule = async (decision: Decision, ways: number[], level?: number, source?: string) => {
    if (busy || ways.length === 0) return;
    setBusy(true);
    const answer = await sendRuling(
      origin,
      { queue, osm_way_ids: ways, decision, ...(decision === "set" ? { step: level ?? step } : {}), ...(source ? { source } : {}), ...(reason.trim() ? { reason: reason.trim() } : {}) },
      csrfFromCookie(document.cookie),
    );
    setBusy(false);
    if (!answer.ok) {
      tell(answer.message);
      return;
    }
    const { rulings, refused, generation } = answer.body;
    if (typeof generation === "number") onStressChanged(generation);
    setReason("");
    setLast(rulings[rulings.length - 1] ?? null);
    const ruled = new Set(rulings.map((r) => r.osm_way_id));
    const rest = all ? shown : shown.filter((r) => !ruled.has(r.osm_way_id));
    const after = shown.slice(index + 1).find((r) => !ruled.has(r.osm_way_id)) ?? rest[0] ?? null;
    if (all) setRoads((old) => old?.map((r) => (ruled.has(r.osm_way_id) ? { ...r, ruling: rulings.find((x) => x.osm_way_id === r.osm_way_id) ?? r.ruling } : r)) ?? old);
    else setRoads(rest);
    // A row is a stretch of ways, each with its own ruling: the rows ruled, not the rulings, leave the count.
    const rowsRuled = shown.filter((r) => ruled.has(r.osm_way_id)).length;
    setTotal((t) => (all ? t : Math.max(0, t - rowsRuled)));
    setSelected(new Set());
    onRuled();
    const road = current && ruled.has(current.osm_way_id) ? current : null;
    const own = road ? (rulings.find((r) => r.osm_way_id === road.osm_way_id) ?? rulings[0]) : null;
    if (ways.length === 1 && road && own) tell(ruledSaid(road, own, after ? after.name || `way ${after.osm_way_id}` : null));
    else tell(answer.body.message);
    if (refused.length && ways.length === 1) tell(refused[0].error);
    if (after) pick(after);
    else if (!all && rest.length === 0) void load(1);
  };

  const undo = async () => {
    if (!last || busy) return;
    setBusy(true);
    const answer = await undoRuling(origin, last.id, csrfFromCookie(document.cookie));
    setBusy(false);
    if (!answer.ok) {
      tell(answer.message);
      return;
    }
    if (typeof answer.body.generation === "number") onStressChanged(answer.body.generation);
    setLast(null);
    onUndone();
    tell(`Undone: ${last.summary}. The road is back in the list.`);
    void load(page, last.osm_way_id);
  };

  const sortBy = (key: SortKey) => {
    const ascending = sort.key === key ? !sort.ascending : key === "name" || key === "area";
    setSort({ key, ascending });
    tell(`Sorted by ${columns.find((c) => c.key === key)?.label ?? "size"}, ${ascending ? "ascending" : "descending"}.`);
  };

  const filterSelect = (name: keyof Filters, text: string, options: { value: string; label: string }[]) =>
    options.length > 0 && (
      <label className="review-filter">
        {text}
        <select
          value={filters[name]}
          onChange={(event) => {
            setFilters({ ...filters, [name]: event.target.value });
          }}
        >
          <option value="">All</option>
          {options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>
    );

  const allShownSelected = shown.length > 0 && shown.every((r) => selected.has(r.osm_way_id));
  const batch = [...selected];
  const batchActions = (["accept", "reject", "set"] as Decision[]).filter((d) => shown.filter((r) => selected.has(r.osm_way_id)).every((r) => r.actions.includes(d)));
  const pending = current ? current.sources.some((s) => s.pending) : false;
  const facts = detail ? factRows(detail.facts, detail.new_facts) : [];
  const sideBySide = queue === "rebuild" && (detail?.new_facts.length ?? 0) > 0;
  const streetView = current ? roadStreetViewUrl(current) : null;

  return (
    <div className="review-queue">
      <h3 id={id("heading")}>{label}</h3>
      {summary && (
        <p className="review-progress">
          {progressText(summary.reviewed, summary.total)}
          {summary.build_id ? ` (build ${summary.build_id})` : ""}
        </p>
      )}
      {summary && summary.note && (
        <p className="hint">
          {summary.note}
          {summary.computed_for ? ` (build ${summary.computed_for})` : ""}: this list fills in once a build sends its report.
        </p>
      )}
      {summary && !summary.note && !summary.wired && <p className="hint">Not wired yet: the rebuild report this list reads is not there. It fills in once a rebuild writes it.</p>}
      {problem && <p role="alert">{problem}</p>}
      <div className="review-filters">
        {filterSelect(
          "kind",
          queue === "rebuild" ? "Change" : queue === "disagreement" ? "Sources that disagree" : "Kind",
          (summary?.kinds ?? []).map((k) => ({ value: k.kind, label: `${k.label} (${k.count})` })),
        )}
        {queue === "disagreement" && filterSelect("source", "Source", (summary?.sources ?? []).map((s) => ({ value: s.source, label: `${s.label} (${s.count})` })))}
        {filterSelect("area", "Area", (summary?.areas ?? []).map((a) => ({ value: a.area, label: `${a.area} (${a.count})` })))}
        <label className="review-filter review-filter-check">
          <input type="checkbox" checked={all} onChange={(event) => setAll(event.target.checked)} />
          Show roads already ruled on
        </label>
      </div>
      <p className="review-said">{said}</p>

      {roads !== null && roads.length === 0 && <p>No roads are waiting in this list{filters.kind || filters.area || filters.source ? " with these filters" : ""}.</p>}
      {shown.length > 0 && (
        <>
          <div className="review-batch" role="group" aria-label="Rule on the selected roads">
            <label>
              <input
                type="checkbox"
                checked={allShownSelected}
                onChange={(event) => setSelected(event.target.checked ? new Set(shown.map((r) => r.osm_way_id)) : new Set())}
              />
              Select every road shown ({shown.length})
            </label>
            <span>{batch.length} selected</span>
            {batch.length > 0 &&
              batchActions.map((d) => (
                <button key={d} type="button" className="secondary" aria-disabled={busy || undefined} onClick={() => void rule(d, batch)}>
                  {decisionLabel(queue, d)}
                  {d === "set" ? ` ${stepText(step)}` : ""} for {batch.length} selected
                </button>
              ))}
          </div>
          <div className="review-table-wrap">
            <table className="review-table">
              <caption className="visually-hidden">
                {label}: {total.toLocaleString("en-US")} roads, page {page}. Up and Down move between roads.
              </caption>
              <thead>
                <tr>
                  <th scope="col">
                    <span className="visually-hidden">Select</span>
                  </th>
                  {columns.map((c) => (
                    <th key={c.label} scope="col" aria-sort={c.key && sort.key === c.key ? (sort.ascending ? "ascending" : "descending") : undefined}>
                      {c.key ? (
                        <button type="button" className="link review-sort" onClick={() => sortBy(c.key as SortKey)}>
                          {c.label}
                        </button>
                      ) : (
                        c.label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((road, i) => {
                  const name = road.name || `Way ${road.osm_way_id}`;
                  const chosen = current?.osm_way_id === road.osm_way_id;
                  return (
                    <tr key={road.osm_way_id} className={chosen ? "review-row-current" : undefined} aria-current={chosen || undefined}>
                      <td>
                        <input
                          type="checkbox"
                          aria-label={`Select ${name}`}
                          checked={selected.has(road.osm_way_id)}
                          onChange={(event) => {
                            const next = new Set(selected);
                            if (event.target.checked) next.add(road.osm_way_id);
                            else next.delete(road.osm_way_id);
                            setSelected(next);
                          }}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          id={id(`r${road.osm_way_id}`)}
                          className="link review-road"
                          aria-label={roadRowLabel(road)}
                          onClick={() => pick(road)}
                          onKeyDown={(event) => {
                            const next = event.key === "ArrowDown" ? shown[i + 1] : event.key === "ArrowUp" ? shown[i - 1] : null;
                            if (!next) return;
                            event.preventDefault();
                            setCurrent(next);
                            setFocusNext(id(`r${next.osm_way_id}`));
                          }}
                        >
                          {name}
                        </button>
                        {road.pieces > 1 && (
                          <span className="hint" aria-hidden="true">
                            {" "}
                            ({piecesText(road)})
                          </span>
                        )}
                      </td>
                      <td>{road.area}</td>
                      {queue === "rebuild" && (
                        <>
                          <td>{stepText(road.old_step, road.old_closed)}</td>
                          <td>{stepText(road.new_step, road.new_closed)}</td>
                          <td>{road.new_source}</td>
                        </>
                      )}
                      {queue !== "rebuild" && <td>{stepText(road.new_step, road.new_closed)}</td>}
                      {queue === "disagreement" && (
                        <>
                          <td>{road.sources.map((s) => `${s.name}: ${stepText(s.level)}`).join("; ")}</td>
                          <td>{road.spread ?? ""}</td>
                        </>
                      )}
                      {queue !== "rebuild" && queue !== "disagreement" && <td>{road.reason}</td>}
                      {(queue === "rebuild" || queue === "disagreement") && <td>{trafficText(road.aadt)}</td>}
                      <td>{road.length}</td>
                      <td>{road.ruling ? road.ruling.summary : "None yet"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="review-pages">
            <button type="button" className="secondary" disabled={page <= 1} onClick={() => void load(page - 1)}>
              Previous page
            </button>
            <span>
              Page {page} of {Math.max(1, Math.ceil(total / perPage))}
            </span>
            <button type="button" className="secondary" disabled={page * perPage >= total} onClick={() => void load(page + 1)}>
              Next page
            </button>
          </div>
        </>
      )}

      {current && (
        <section className="review-card" aria-labelledby={id("card")}>
          <h4
            id={id("card")}
            tabIndex={-1}
            aria-describedby={id("card-keys")}
            onKeyDown={(event) => {
              if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
              event.preventDefault();
              move(event.key === "ArrowDown" ? 1 : -1);
            }}
          >
            {roadHeading(current)}
          </h4>
          <p id={id("card-keys")} className="visually-hidden">
            Up and Down go to the road before or after this one.
          </p>
          <p className="review-reason">{current.reason}</p>
          <dl className="review-levels">
            {current.queue === "rebuild" && (
              <>
                <dt>Before</dt>
                <dd>
                  {current.old_words}
                  {current.old_rule ? `. ${current.old_rule}` : ""}
                  {current.old_source ? ` (decided by ${current.old_source})` : ""}
                </dd>
              </>
            )}
            <dt>{current.queue === "rebuild" ? "After" : "Now"}</dt>
            <dd>
              {current.new_words}
              {current.new_rule ? `. ${current.new_rule}` : ""}
              {current.new_source ? ` (decided by ${current.new_source})` : ""}
            </dd>
            <dt>Length</dt>
            <dd>
              {current.length}
              {current.pieces > 1 ? `, ${piecesText(current)} ruled together` : ""}
            </dd>
            <dt>Traffic</dt>
            <dd>{trafficText(current.aadt)}</dd>
          </dl>
          {streetView && (
            <p className="review-street-view">
              <a href={streetView} target="_blank" rel="noopener noreferrer" aria-describedby={id("sv-note")}>
                {STREET_VIEW_TEXT}
              </a>{" "}
              <span id={id("sv-note")} className="hint">
                {STREET_VIEW_NOTE}
              </span>
            </p>
          )}
          {settled && settled.osm_way_id === current.osm_way_id && settled.point && (
            <StreetPhotoView title={current.name || `Way ${current.osm_way_id}`} point={settled.point} wayId={settled.osm_way_id} path={PHOTO_PATH} />
          )}
          {current.sources.length > 0 && (
            <table className="review-sources">
              <caption>Every rating this road holds</caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Level</th>
                  <th scope="col">
                    <span className="visually-hidden">Use it</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {current.sources.map((s) => (
                  <tr key={s.key}>
                    <th scope="row">{s.name}</th>
                    <td>{stepText(s.level)}</td>
                    <td>
                      {/* A pending agency's level is information only: the admin picks a level below, as their own. */}
                      {!s.pending && current.actions.includes("set") && s.level !== current.new_step && (
                        <button type="button" className="secondary" aria-disabled={busy || undefined} onClick={() => void rule("set", [current.osm_way_id], s.level, s.key)}>
                          Use {stepText(s.level)}
                          <span className="visually-hidden"> from {s.name}</span>
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="review-rule" role="group" aria-labelledby={id("rule-heading")}>
            <h5 id={id("rule-heading")}>Ruling</h5>
            {current.ruling && <p>Ruled: {current.ruling.summary}.</p>}
            <label className="review-reason-field">
              Private reason (optional; never shown to riders)
              <input type="text" maxLength={500} value={reason} aria-describedby={pending ? id("pending-note") : undefined} onChange={(event) => setReason(event.target.value)} />
            </label>
            {pending && (
              <p id={id("pending-note")} className="hint">
                Don&apos;t quote pending agencies&apos; data.
              </p>
            )}
            <div className="stress-editor-buttons">
              {current.actions
                .filter((d) => d !== "set")
                .map((d) => (
                  <button key={d} type="button" aria-describedby={id("card")} aria-disabled={busy || undefined} onClick={() => void rule(d, [current.osm_way_id])}>
                    {rulingLabel(current, d)}
                  </button>
                ))}
              {current.actions.includes("set") && (
                <>
                  <label className="review-step">
                    Level
                    <select value={step} onChange={(event) => setStep(Number(event.target.value))}>
                      {REVIEW_STEPS.map((s) => (
                        <option key={s} value={s}>
                          {stepText(s)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button type="button" aria-describedby={id("card")} aria-disabled={busy || undefined} onClick={() => void rule("set", [current.osm_way_id])}>
                    Set {stepText(step)}
                  </button>
                </>
              )}
            </div>
            <div className="stress-editor-buttons">
              <button type="button" className="secondary" onClick={() => move(-1)}>
                Previous road
              </button>
              <button type="button" className="secondary" onClick={() => move(1)}>
                Next road
              </button>
              {last && last.can_undo && (
                <button type="button" className="secondary" aria-disabled={busy || undefined} onClick={() => void undo()}>
                  Undo: {last.summary}
                </button>
              )}
            </div>
          </div>
          {facts.length > 0 && (
            <table className="review-facts">
              <caption>{sideBySide ? "The facts behind the rating, in the map now and in the new build" : "The facts behind the rating"}</caption>
              {sideBySide && (
                <thead>
                  <tr>
                    <th scope="col">Fact</th>
                    <th scope="col">Map now</th>
                    <th scope="col">New build</th>
                  </tr>
                </thead>
              )}
              <tbody>
                {facts.map((f) => (
                  <tr key={f.label}>
                    <th scope="row">{f.label}</th>
                    <td>{f.now || "—"}</td>
                    {sideBySide && <td>{f.next || "—"}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {detail && (
            <>
              <h5>History</h5>
              {detail.history.length === 0 ? (
                <p>No edits, overrides or rulings yet.</p>
              ) : (
                <ul className="review-history">
                  {detail.history.map((h, i) => (
                    <li key={i}>
                      {h.at ? `${h.at.slice(0, 10)}: ` : ""}
                      {h.what}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}
    </div>
  );
}
