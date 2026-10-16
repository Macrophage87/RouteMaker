/**
 * Review mode (lib/review.ts; the owner, 2026-10-16: "Basically we'd have 3 modes for people who have admin access
 * go/plan/review"), beside Go and Plan for an instance admin (or a closures reviewer, who sees the closures only).
 *
 * Desktop first, a split view: the panel holds every list with its count (a nav of toggle buttons), the chosen
 * list as a table with sortable columns, and the chosen road's card (its levels, every rating it holds side by side,
 * the facts behind them and its history) with the ruling buttons; the map beside it zooms to the road and, for
 * Review's queues, draws the list's roads coloured by the size of the change or disagreement. A tap on a road there
 * opens its card. The riders' suggestions, Mass Ride hazard reports and closure reports keep their own reviews
 * (SuggestionReview.tsx, ClosureReview.tsx), hosted here.
 *
 * Keyboard and screen readers: every control is a real button, select, checkbox or text box with a name; in the
 * table, Up and Down move between the roads' buttons, and choosing one moves the focus to its card's heading; the
 * card has Previous road and Next road. Every result is said in the app's polite live region (`announce`), and
 * the progress line ("12 of 601 reviewed") follows every ruling. Levels are said in words as well as numbers;
 * lengths in miles first, kilometres after.
 *
 * A ruling informed by an agency whose public use is still pending is the admin's own: its private reason is
 * never filled in from that row.
 */
import { useCallback, useEffect, useId, useState } from "react";
import type { GeoJSONSource, Map as MapLibreMap, MapMouseEvent } from "maplibre-gl";
import { SuggestionReview } from "./SuggestionReview.tsx";
import { ClosureReview } from "./ClosureReview.tsx";
import { useMap } from "./app/mapOverlay.ts";
import { HAZARD_REVIEW } from "./lib/reviewSources.ts";
import { csrfFromCookie } from "./lib/stressEditor.ts";
import {
  DEFAULT_LIST,
  LISTS,
  NO_FILTERS,
  REVIEW_STEPS,
  decisionLabel,
  fetchOverlay,
  fetchQueues,
  fetchRoadDetail,
  fetchRoads,
  isQueue,
  progressText,
  roadHeading,
  ruledSaid,
  sendRuling,
  sizeColour,
  sortRoads,
  stepText,
  trafficText,
  undoRuling,
  type Decision,
  type Filters,
  type ListKey,
  type QueueKey,
  type QueueSummary,
  type ReviewRoad,
  type RoadDetail,
  type Ruling,
  type SortKey,
} from "./lib/review.ts";

const CURRENT = "review-current";
const OVERLAY = "review-overlay";
const OVERLAY_MIN_ZOOM = 10;

export interface ReviewModeProps {
  getMap: () => MapLibreMap | null;
  announce: (text: string) => void;
  /** An instance admin: Review's queues, the suggestions and the hazards (a closures reviewer sees the closures). */
  admin: boolean;
  /** A stress change was made: the map asks for its tiles again. */
  onStressChanged: (generation: number) => void;
  onHazardsChanged: () => void;
  /** The list to open on (Suggest's Review button opens the riders' suggestions). */
  list?: ListKey;
  onList?: (list: ListKey) => void;
}

export function ReviewMode({ getMap, announce, admin, onStressChanged, onHazardsChanged, list: wanted, onList }: ReviewModeProps) {
  const base = useId();
  const [list, setList] = useState<ListKey>(wanted ?? (admin ? DEFAULT_LIST : "closures"));
  const [queues, setQueues] = useState<QueueSummary[] | null>(null);
  const [problem, setProblem] = useState("");
  const origin = window.location.origin;

  useEffect(() => {
    if (wanted) setList(wanted);
  }, [wanted]);

  const loadQueues = useCallback(async () => {
    if (!admin) return;
    const found = await fetchQueues(origin);
    if (typeof found === "string") setProblem(found);
    else {
      setProblem("");
      setQueues(found);
    }
  }, [admin, origin]);

  useEffect(() => {
    void loadQueues();
  }, [loadQueues]);

  const lists = LISTS.filter((l) => (admin ? true : l.key === "closures"));
  const summary = (key: ListKey) => queues?.find((q) => q.queue === key) ?? null;
  const choose = (key: ListKey) => {
    setList(key);
    onList?.(key);
    const label = LISTS.find((l) => l.key === key)?.label ?? "";
    const s = isQueue(key) ? summary(key) : null;
    announce(s ? `${label}: ${progressText(s.reviewed, s.total)}.` : `${label}.`);
  };

  return (
    <section className="review-mode" aria-labelledby={`${base}-heading`}>
      <h2 id={`${base}-heading`}>Review</h2>
      {problem && <p role="alert">{problem}</p>}
      <div className="review-layout">
        <nav className="review-lists" aria-label="Review lists">
          <ul>
            {lists.map((l) => {
              const s = isQueue(l.key) ? summary(l.key) : null;
              return (
                <li key={l.key}>
                  <button type="button" className="review-list-button" aria-pressed={list === l.key} onClick={() => choose(l.key)}>
                    <span className="review-list-name">{l.label}</span>
                    {s && <span className="review-list-count">{s.wired ? progressText(s.reviewed, s.total) : "Not wired yet"}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
        <div className="review-main">
          {isQueue(list) && admin ? (
            <QueueView
              key={list}
              queue={list}
              summary={summary(list)}
              label={LISTS.find((l) => l.key === list)?.label ?? ""}
              getMap={getMap}
              announce={announce}
              onStressChanged={onStressChanged}
              onRuled={() => void loadQueues()}
            />
          ) : list === "suggestions" && admin ? (
            <SuggestionReview onStressChanged={onStressChanged} />
          ) : list === "hazards" && admin ? (
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

interface QueueViewProps {
  queue: QueueKey;
  label: string;
  summary: QueueSummary | null;
  getMap: () => MapLibreMap | null;
  announce: (text: string) => void;
  onStressChanged: (generation: number) => void;
  onRuled: () => void;
}

function QueueView({ queue, label, summary, getMap, announce, onStressChanged, onRuled }: QueueViewProps) {
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
  const [detail, setDetail] = useState<RoadDetail | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [step, setStep] = useState(3);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<Ruling | null>(null);
  const [said, setSaid] = useState("");
  const [focusNext, setFocusNext] = useState<string | null>(null);
  const [overlayAsk, setOverlayAsk] = useState(0);
  const perPage = 50;
  const columns = COLUMNS[queue === "rebuild" ? "rebuild" : queue === "disagreement" ? "disagreement" : "other"];
  const say = (text: string) => {
    setSaid(text);
    announce(text);
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
      const next = (keep !== null && found.items.find((r) => r.osm_way_id === keep)) || found.items[0] || null;
      setCurrent(next);
      return found;
    },
    [origin, queue, filters, all],
  );

  useEffect(() => {
    void load(1);
  }, [load]);

  useEffect(() => {
    if (focusNext === null) return;
    document.getElementById(focusNext)?.focus();
    setFocusNext(null);
  }, [focusNext, roads, current]);

  // The chosen road's facts and history.
  useEffect(() => {
    setDetail(null);
    if (!current) return;
    let live = true;
    void fetchRoadDetail(origin, current.osm_way_id).then((found) => {
      if (live && typeof found !== "string") setDetail(found);
    });
    return () => {
      live = false;
    };
  }, [origin, current]);

  // The map: the chosen road highlighted and zoomed to; the list's roads in view, coloured by size.
  useMap(
    getMap,
    (map) => {
      const empty = { type: "FeatureCollection", features: [] };
      for (const sourceId of [OVERLAY, CURRENT]) if (!map.getSource(sourceId)) map.addSource(sourceId, { type: "geojson", data: empty as never });
      if (!map.getLayer(OVERLAY))
        map.addLayer({
          id: OVERLAY,
          type: "line",
          source: OVERLAY,
          paint: {
            "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2, 16, 6],
            "line-opacity": ["case", ["get", "ruled"], 0.35, 0.85],
            "line-color": ["step", ["get", "size"], sizeColour(0.5), 1, sizeColour(1), 2, sizeColour(2)],
          },
        });
      if (!map.getLayer(CURRENT))
        map.addLayer({ id: CURRENT, type: "line", source: CURRENT, paint: { "line-width": 8, "line-color": "#6a1b9a", "line-opacity": 0.9 } });
      let asked = 0;
      const refresh = () => {
        const ask = ++asked;
        const source = map.getSource(OVERLAY) as GeoJSONSource | undefined;
        if (map.getZoom() < OVERLAY_MIN_ZOOM) {
          source?.setData(empty as never);
          return;
        }
        const b = map.getBounds();
        void fetchOverlay(origin, queue, filters, { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() }).then((found) => {
          if (ask === asked && typeof found !== "string") (map.getSource(OVERLAY) as GeoJSONSource | undefined)?.setData(found as never);
        });
      };
      const onClick = (event: MapMouseEvent & { features?: Array<{ properties?: Record<string, unknown> }> }) => {
        const way = Number(event.features?.[0]?.properties?.way);
        if (Number.isFinite(way)) void openWay(way);
      };
      const enter = () => (map.getCanvas().style.cursor = "pointer");
      const leave = () => (map.getCanvas().style.cursor = "");
      map.on("moveend", refresh);
      map.on("click", OVERLAY, onClick);
      map.on("mouseenter", OVERLAY, enter);
      map.on("mouseleave", OVERLAY, leave);
      refresh();
      return () => {
        map.off("moveend", refresh);
        map.off("click", OVERLAY, onClick);
        map.off("mouseenter", OVERLAY, enter);
        map.off("mouseleave", OVERLAY, leave);
        for (const layer of [CURRENT, OVERLAY]) if (map.getLayer(layer)) map.removeLayer(layer);
        for (const sourceId of [CURRENT, OVERLAY]) if (map.getSource(sourceId)) map.removeSource(sourceId);
      };
    },
    [queue, filters, overlayAsk],
  );

  useMap(
    getMap,
    (map) => {
      const source = map.getSource(CURRENT) as GeoJSONSource | undefined;
      source?.setData((current?.geometry ? { type: "Feature", geometry: current.geometry, properties: {} } : { type: "FeatureCollection", features: [] }) as never);
      if (current?.bbox) {
        const [w, s, e, n] = current.bbox;
        const panel = document.getElementById("route-planner")?.getBoundingClientRect();
        const left = panel && panel.right < window.innerWidth * 0.8 ? panel.right + 24 : 40;
        map.fitBounds(
          [
            [w, s],
            [e, n],
          ],
          { padding: { left, right: 40, top: 60, bottom: 60 }, maxZoom: 17, duration: 400 },
        );
      }
    },
    [current, overlayAsk],
  );

  // A tap on a road in the overlay: its card, with the list as it is.
  const openWay = async (way: number) => {
    const found = await fetchRoads(origin, queue, NO_FILTERS, { all: true, way });
    if (typeof found === "string" || found.items.length === 0) return;
    const road = found.items[0];
    setCurrent(road);
    say(`${roadHeading(road)}.`);
    setFocusNext(id("card"));
  };

  const shown = roads ? sortRoads(roads, sort.key, sort.ascending) : [];
  const index = current ? shown.findIndex((r) => r.osm_way_id === current.osm_way_id) : -1;
  const pick = (road: ReviewRoad, focusCard = true) => {
    setCurrent(road);
    if (focusCard) setFocusNext(id("card"));
  };
  const move = (by: number) => {
    const next = shown[index + by];
    if (next) pick(next);
    else say(by > 0 ? "That is the last road on this page." : "That is the first road on this page.");
  };

  const rule = async (decision: Decision, ways: number[], level?: number) => {
    if (busy || ways.length === 0) return;
    setBusy(true);
    const answer = await sendRuling(
      origin,
      { queue, osm_way_ids: ways, decision, ...(decision === "set" ? { step: level ?? step } : {}), ...(reason.trim() ? { reason: reason.trim() } : {}) },
      csrfFromCookie(document.cookie),
    );
    setBusy(false);
    if (!answer.ok) {
      say(answer.message);
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
    setTotal((t) => (all ? t : Math.max(0, t - ruled.size)));
    setSelected(new Set());
    onRuled();
    setOverlayAsk((n) => n + 1);
    const road = current && ruled.has(current.osm_way_id) ? current : null;
    if (ways.length === 1 && road && rulings[0]) say(ruledSaid(road, rulings[0], after ? after.name || `way ${after.osm_way_id}` : null));
    else say(answer.body.message);
    if (refused.length && ways.length === 1) say(refused[0].error);
    if (after) pick(after);
    else if (!all && rest.length === 0) void load(1);
  };

  const undo = async () => {
    if (!last || busy) return;
    setBusy(true);
    const answer = await undoRuling(origin, last.id, csrfFromCookie(document.cookie));
    setBusy(false);
    if (!answer.ok) {
      say(answer.message);
      return;
    }
    if (typeof answer.body.generation === "number") onStressChanged(answer.body.generation);
    setLast(null);
    onRuled();
    setOverlayAsk((n) => n + 1);
    say(`Undone: ${last.summary}. The road is back in the list.`);
    void load(page, last.osm_way_id);
  };

  const sortBy = (key: SortKey) => {
    const ascending = sort.key === key ? !sort.ascending : key === "name" || key === "area";
    setSort({ key, ascending });
    say(`Sorted by ${columns.find((c) => c.key === key)?.label ?? "size"}, ${ascending ? "ascending" : "descending"}.`);
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

  return (
    <div className="review-queue">
      <h3 id={id("heading")}>{label}</h3>
      {summary && (
        <p className="review-progress">
          {progressText(summary.reviewed, summary.total)}
          {summary.build_id ? ` (build ${summary.build_id})` : ""}
        </p>
      )}
      {summary && !summary.wired && <p className="hint">Not wired yet: the rebuild report this list reads is not there. It fills in once a rebuild writes it.</p>}
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
          <h4 id={id("card")} tabIndex={-1}>
            {roadHeading(current)}
          </h4>
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
            <dd>{current.length}</dd>
            <dt>Traffic</dt>
            <dd>{trafficText(current.aadt)}</dd>
          </dl>
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
                      {current.actions.includes("set") && s.level !== current.new_step && (
                        <button type="button" className="secondary" aria-disabled={busy || undefined} onClick={() => void rule("set", [current.osm_way_id], s.level)}>
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
              <input type="text" maxLength={500} value={reason} onChange={(event) => setReason(event.target.value)} />
            </label>
            <div className="stress-editor-buttons">
              {current.actions
                .filter((d) => d !== "set")
                .map((d) => (
                  <button key={d} type="button" aria-describedby={id("card")} aria-disabled={busy || undefined} onClick={() => void rule(d, [current.osm_way_id])}>
                    {decisionLabel(queue, d)}
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
          {detail && detail.facts.length > 0 && (
            <table className="review-facts">
              <caption>The facts behind the rating</caption>
              <tbody>
                {detail.facts.map((f, i) => (
                  <tr key={`${f.label}-${i}`}>
                    <th scope="row">{f.label}</th>
                    <td>
                      {f.value}
                      {f.source ? <span className="review-source"> ({f.source})</span> : null}
                    </td>
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
