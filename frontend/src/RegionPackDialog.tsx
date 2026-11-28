// Settings' maps for no signal, the popout (RegionPackSetting.tsx opens it, loaded on first use).
import { useEffect, useId, useRef, useState } from "react";
import { language } from "./lib/i18n.ts";
import { askPersist } from "./lib/offlineRouteStore.ts";
import { sizeText } from "./lib/offlineRoutes.ts";
import {
  PACK_CLOSE,
  PACK_DELETE,
  PACK_DELETE_ALL,
  PACK_DOWNLOAD,
  PACK_DOWNLOADING,
  PACK_FAILED,
  PACK_IN_ALL,
  PACK_KEPT,
  PACK_LABEL,
  PACK_MAP_LABEL,
  PACK_NO_LIST,
  PACK_NO_ROOM,
  PACK_NONE_KEPT,
  PACK_ON_PHONE,
  PACK_WAITING,
  areaName,
  covers,
  deleteName,
  downloadAllText,
  downloadName,
  downloadPack,
  downloads,
  mapDateText,
  onDownloads,
  onPhoneText,
  removeAll,
  removePack,
  storedAreas,
  type Areas,
  type DownloadOutcome,
  type KeptPack,
  type PackList,
} from "./lib/regionPack.ts";

const totalBytes = (kept: KeptPack[]) => kept.reduce((sum, k) => sum + k.bytes, 0);

const OUTCOME_SAID: Record<DownloadOutcome, string> = {
  kept: PACK_KEPT,
  failed: PACK_FAILED,
  "no-room": PACK_NO_ROOM,
  cancelled: "",
};

/** The popout: what is on this phone, the map of the areas, each area's Download or Delete, and all of them at once. */
export function RegionPackDialog({
  open,
  onClose,
  list,
  kept,
  onKept,
}: {
  open: boolean;
  onClose: () => void;
  /** The packs on offer: undefined while asked, null with no signal. */
  list: PackList | null | undefined;
  kept: KeptPack[];
  onKept: () => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const opener = useRef<Element | null>(null);
  const headingId = useId();
  const [queue, setQueue] = useState(() => downloads());
  // Empty at first, so a screen reader hears each change of the live line.
  const [said, setSaid] = useState("");

  useEffect(() => onDownloads(() => setQueue(downloads())), []);
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement;
      setQueue(downloads());
      dialog.showModal?.();
      // The heading, not the first row's button: Enter at once must never delete a kept area.
      dialog.querySelector<HTMLElement>("h2")?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
      if (opener.current instanceof HTMLElement && opener.current.isConnected)
        opener.current.focus();
    }
  }, [open]);

  const whole = list?.packs.find((p) => p.area?.whole || p.id === "all");
  const wholeKept = kept.find((k) => k.id === (whole?.id ?? "all"));
  // The areas: as listed; with no signal, the ones kept.
  const rows = list
    ? list.packs
        .filter((p) => p !== whole)
        .map((p) => ({
          id: p.id,
          name: areaName(p.id, p.name),
          bytes: p.bytes,
        }))
    : kept
        .filter((k) => k !== wholeKept)
        .map((k) => ({
          id: k.id,
          name: areaName(k.id, k.name),
          bytes: k.bytes,
        }));
  const busy = (id: string) =>
    queue.active === id || queue.waiting.includes(id);

  const get = (id: string) => {
    const pack = list?.packs.find((p) => p.id === id);
    if (!list || !pack) {
      setSaid(PACK_NO_LIST);
      return;
    }
    void askPersist();
    setSaid(PACK_DOWNLOADING);
    void downloadPack(pack, list).then((outcome) => {
      onKept();
      setSaid(OUTCOME_SAID[outcome]);
    });
  };
  const drop = (id: string) => {
    void removePack(id).then(onKept);
    setSaid("");
  };
  const dropAll = () => {
    void removeAll().then(onKept);
    setSaid("");
  };

  const date = kept.length
    ? mapDateText(
        kept
          .map((k) => k.buildId)
          .sort()
          .at(-1) ?? "",
        language(),
      )
    : "";
  const areas: Areas | null = list ? areasOf(list) : storedAreas();
  const keptIds = new Set(kept.map((k) => k.id));
  return (
    <dialog
      ref={dialogRef}
      className="ask-dialog region-pack-dialog"
      aria-labelledby={headingId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
    >
      {open && (
        <>
          <h2 id={headingId} tabIndex={-1}>
            {PACK_LABEL}
          </h2>
          <p className="region-pack-onphone">
            <strong>
              {kept.length
                ? onPhoneText(sizeText(totalBytes(kept)))
                : PACK_NONE_KEPT}
            </strong>
            {date && (
              <>
                <br />
                {date}
              </>
            )}
          </p>
          {areas && (
            <AreaMap
              areas={areas}
              order={rows.map((r) => r.id)}
              kept={wholeKept ? new Set(rows.map((r) => r.id)) : keptIds}
            />
          )}
          <ol className="region-pack-list">
            {rows.map((row, index) => {
              const has = keptIds.has(row.id);
              return (
                <li key={row.id} className="region-pack-area">
                  <span
                    className={`region-pack-badge area-${index + 1}`}
                    aria-hidden="true"
                  >
                    {index + 1}
                  </span>
                  <span className="region-pack-words">
                    <strong>{row.name}</strong>
                    <span className="hint">
                      {wholeKept
                        ? PACK_IN_ALL
                        : queue.active === row.id
                          ? PACK_DOWNLOADING
                          : queue.waiting.includes(row.id)
                            ? PACK_WAITING
                            : has
                              ? `${PACK_ON_PHONE} · ${sizeText(row.bytes)}`
                              : sizeText(row.bytes)}
                    </span>
                  </span>
                  {!wholeKept && (has || list) && (
                    // One button that changes between Download and Delete (and is only marked unavailable while the
                    // whole map or this area downloads), so the focus stays on it.
                    <button
                      type="button"
                      className={has ? "secondary danger" : "secondary"}
                      aria-label={
                        has ? deleteName(row.name) : downloadName(row.name)
                      }
                      aria-disabled={
                        !has && (busy(row.id) || (!!whole && busy(whole.id)))
                      }
                      onClick={() => {
                        if (has) drop(row.id);
                        else if (!busy(row.id) && !(whole && busy(whole.id)))
                          get(row.id);
                      }}
                    >
                      {has ? PACK_DELETE : PACK_DOWNLOAD}
                    </button>
                  )}
                </li>
              );
            })}
          </ol>
          <p className="hint region-pack-status" role="status">
            {said || (list === null ? PACK_NO_LIST : "")}
          </p>
          <div className="closure-choices">
            {whole && !wholeKept && (
              <button
                type="button"
                className="primary"
                // Marked unavailable, not disabled, so the focus stays on it once it starts.
                aria-disabled={busy(whole.id)}
                onClick={() => {
                  if (!busy(whole.id)) get(whole.id);
                }}
              >
                {busy(whole.id)
                  ? PACK_DOWNLOADING
                  : downloadAllText(sizeText(whole.bytes))}
              </button>
            )}
            {kept.length > 0 && (
              <button
                type="button"
                className="secondary danger"
                onClick={dropAll}
              >
                {PACK_DELETE_ALL}
              </button>
            )}
            <button type="button" className="secondary" onClick={onClose}>
              {PACK_CLOSE}
            </button>
          </div>
        </>
      )}
    </dialog>
  );
}

function areasOf(list: PackList): Areas | null {
  const areas: Areas["areas"] = {};
  for (const p of list.packs) if (p.area) areas[p.id] = p.area;
  return Object.keys(areas).length ? { box: list.box, areas } : null;
}

// Towns for finding one's way on the map: names on every map, so not translated.
const TOWNS: readonly [string, number, number][] = [
  ["Washington", -77.037, 38.907],
  ["Baltimore", -76.612, 39.29],
  ["Frederick", -77.41, 39.414],
  ["Annapolis", -76.492, 38.978],
  ["Leesburg", -77.564, 39.116],
  ["Fredericksburg", -77.461, 38.303],
  ["Martinsburg", -77.964, 39.456],
  ["Waldorf", -76.939, 38.624],
];

/**
 * The areas on a small map (Stephen, 2026-11-15: "Perhaps show a map of what covers what"), numbered as their rows are,
 * the kept ones filled darker; drawn from the areas' outlines with a few towns, so it shows with no signal too. The area
 * with no outline is the box less the others, drawn under them.
 */
function AreaMap({
  areas,
  order,
  kept,
}: {
  areas: Areas;
  order: string[];
  kept: ReadonlySet<string>;
}) {
  const maskId = useId().replace(/:/g, "");
  // The home area's regions; a later area's own pack (separate) is far off the picture and is listed only.
  const outlined = Object.entries(areas.areas).filter(([, a]) => a.outline && !a.separate);
  const xs = outlined.flatMap(([, a]) => a.outline!.map((p) => p[0]));
  const ys = outlined.flatMap(([, a]) => a.outline!.map((p) => p[1]));
  const [w, s, e, n] = areas.box ?? [
    Math.min(...xs),
    Math.min(...ys),
    Math.max(...xs),
    Math.max(...ys),
  ];
  if (![w, s, e, n].every(Number.isFinite)) return null;
  const k = Math.cos((((s + n) / 2) * Math.PI) / 180);
  const W = 320;
  const scale = W / ((e - w) * k);
  const H = Math.round((n - s) * scale);
  const xy = ([lon, lat]: readonly [number, number]) =>
    [((lon - w) * k * scale).toFixed(1), ((n - lat) * scale).toFixed(1)].join(
      ",",
    );
  const path = (outline: readonly (readonly [number, number])[]) =>
    `M${outline.map(xy).join("L")}Z`;
  const number = (id: string) => order.indexOf(id) + 1;
  const beltway = outlined.find(([, a]) => !a.outsideBeltway);
  const rest = Object.entries(areas.areas).find(
    ([, a]) => !a.outline && !a.whole,
  );
  // Under the rest: the box; over it, the outlined areas, the Beltway's last.
  const drawn = [
    ...outlined.filter(([id]) => id !== beltway?.[0]),
    ...(beltway ? [beltway] : []),
  ];
  // Where an area's number goes: the middle of the points of a grid that fall inside it (the Beltway cut out, the rest
  // less the others), so a long or hollowed area still gets its number inside.
  const labelAt = (id: string): [number, number] | null => {
    const inside: [number, number][] = [];
    for (let i = 1; i < 24; i++)
      for (let j = 1; j < 24; j++) {
        const at: [number, number] = [
          w + ((e - w) * i) / 24,
          s + ((n - s) * j) / 24,
        ];
        if (covers(id, at, areas)) inside.push(at);
      }
    if (!inside.length) return null;
    const mean = [
      inside.reduce((t, p) => t + p[0], 0) / inside.length,
      inside.reduce((t, p) => t + p[1], 0) / inside.length,
    ];
    return inside.reduce((best, p) =>
      Math.hypot(p[0] - mean[0], p[1] - mean[1]) <
      Math.hypot(best[0] - mean[0], best[1] - mean[1])
        ? p
        : best,
    );
  };
  return (
    <svg
      className="region-pack-map"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={PACK_MAP_LABEL}
    >
      {/* The rest: the box less the outlined areas, so its fill never tints theirs. */}
      <mask id={`${maskId}-rest`}>
        <rect x="0" y="0" width={W} height={H} fill="#fff" />
        {outlined.map(([id, a]) => (
          <path key={id} d={path(a.outline!)} fill="#000" />
        ))}
      </mask>
      {rest && number(rest[0]) > 0 && (
        <rect
          x="0"
          y="0"
          width={W}
          height={H}
          mask={`url(#${maskId}-rest)`}
          className={`area-${number(rest[0])}${kept.has(rest[0]) ? " kept" : ""}`}
        />
      )}
      {drawn.map(([id, a]) =>
        number(id) > 0 ? (
          <path
            key={id}
            d={path(a.outline!)}
            className={`area-${number(id)}${kept.has(id) ? " kept" : ""}`}
          />
        ) : null,
      )}
      {TOWNS.filter(
        ([, lon, lat]) => lon > w && lon < e && lat > s && lat < n,
      ).map(([name, lon, lat]) => {
        const [x, y] = xy([lon, lat]).split(",").map(Number);
        return (
          <g key={name} className="region-pack-town" aria-hidden="true">
            <circle cx={x} cy={y} r="2.5" />
            <text x={x + 4} y={y + 4}>
              {name}
            </text>
          </g>
        );
      })}
      {[...drawn, ...(rest ? [rest] : [])].map(([id]) => {
        const at = number(id) > 0 ? labelAt(id) : null;
        if (!at) return null;
        const [x, y] = xy(at).split(",").map(Number);
        return (
          <g
            key={`n-${id}`}
            className={`region-pack-number area-${number(id)}`}
            aria-hidden="true"
          >
            <circle cx={x} cy={y} r="10" />
            <text x={x} y={y + 4.5} textAnchor="middle">
              {number(id)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
