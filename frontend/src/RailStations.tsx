import { METRO_LINES, PENN_LABEL, type RailVisibility } from "./lib/railStations.ts";
import { PENN_COLOUR } from "./lib/railData.ts";
import { OUTLINE } from "./lib/stationIcons.ts";
import { LayerSection } from "./lib/layerSection.ts";

// The map's icons are ringed in OUTLINE, for the light base map; the legend
// sits on the panel, which is dark in the dark theme, so its ring follows the
// theme (--rail-ring in styles.css).
const RING = { stroke: "var(--rail-ring)" };

/** One wedge of a legend pie, as an SVG path: wedge k of n, clockwise from twelve o'clock. */
function wedge(k: number, n: number, c: number, r: number): string {
  const at = (i: number) => {
    const a = (2 * Math.PI * i) / n;
    return `${(c + r * Math.sin(a)).toFixed(2)} ${(c - r * Math.cos(a)).toFixed(2)}`;
  };
  return `M ${c} ${c} L ${at(k)} A ${r} ${r} 0 0 1 ${at(k + 1)} Z`;
}

function Swatch({ colours, square = false }: { colours: readonly string[]; square?: boolean }) {
  const size = 16;
  const c = size / 2;
  const r = c - 1;
  return (
    <svg width={size} height={size} aria-hidden="true" className="rail-swatch">
      {square ? (
        <rect x="1.5" y="1.5" width={size - 3} height={size - 3} fill={colours[0]} style={RING} strokeWidth="1.5" />
      ) : colours.length === 1 ? (
        <circle cx={c} cy={c} r={r - 0.5} fill={colours[0]} style={RING} strokeWidth="1.5" />
      ) : (
        <>
          {colours.map((colour, k) => (
            <path key={k} d={wedge(k, colours.length, c, r)} fill={colour} stroke="#ffffff" strokeWidth="1" />
          ))}
          <circle cx={c} cy={c} r={r - 0.5} fill="none" style={RING} strokeWidth="1.5" />
        </>
      )}
    </svg>
  );
}

function ElevatorSwatch() {
  return (
    <svg width="16" height="16" aria-hidden="true" className="rail-swatch">
      <rect x="0.5" y="0.5" width="15" height="15" fill={OUTLINE} stroke="#ffffff" strokeWidth="1" />
      <path d="M 8 2.6 L 4.8 7 L 11.2 7 Z M 8 13.4 L 4.8 9 L 11.2 9 Z" fill="#ffffff" />
    </svg>
  );
}

interface Props {
  visibility: RailVisibility;
  onChange: (visibility: RailVisibility) => void;
}

/** Layers' one line for the section; RAIL_HELP, by the legend, says the rest. */
export const RAIL_HINT = "Tap a station to start, end or pass through it.";
export const RAIL_HELP =
  "The route uses a station's elevator, or its nearest entrance where none is listed. The station's card also links to " +
  "its WMATA page or the MARC Penn Line timetable, and the road info panel offers them for a station nearby.";

/**
 * The Layers sheet's rail stations section (lib/layerSection.ts): one row, its switch for Metro and MARC
 * together, and inside, each one's own checkbox and one line. The legend and the longer help are behind
 * Layers' Legend button (RailStationsLegend).
 */
export function RailStationsSection({ visibility, onChange }: Props) {
  return (
    <LayerSection
      id="rail"
      title="Rail stations"
      headingId="rail-heading"
      layers={[
        { key: "metro", label: "Metro", on: visibility.metro },
        { key: "marc", label: PENN_LABEL, on: visibility.marc },
      ]}
      onLayers={(next) => onChange({ ...visibility, metro: next.metro, marc: next.marc })}
    >
      <label className="toggle">
        <input
          type="checkbox"
          checked={visibility.metro}
          onChange={(event) => onChange({ ...visibility, metro: event.target.checked })}
        />
        Metro
      </label>
      <label className="toggle">
        <input
          type="checkbox"
          checked={visibility.marc}
          onChange={(event) => onChange({ ...visibility, marc: event.target.checked })}
        />
        {PENN_LABEL}, Washington to Baltimore
      </label>
      <p className="hint">{RAIL_HINT}</p>
    </LayerSection>
  );
}

/** The Legend sheet's rail stations rows and help (moved from Layers, the owner's "less wordy", 2026-10-12). */
export function RailStationsLegend() {
  const metro = Object.values(METRO_LINES);
  return (
    <>
      <ul className="legend rail-legend" aria-label="Rail stations legend">
        {metro.map((line) => (
          <li key={line.key}>
            <Swatch colours={[line.color]} />
            <span className="stress-label">{line.label} line</span>
          </li>
        ))}
        <li>
          <Swatch colours={[PENN_COLOUR]} square />
          <span className="stress-label">{PENN_LABEL} (square)</span>
        </li>
        <li>
          <Swatch colours={[METRO_LINES.red.color, METRO_LINES.blue.color, METRO_LINES.orange.color]} />
          <span className="stress-label">Several lines: one slice each</span>
        </li>
        <li>
          <ElevatorSwatch />
          <span className="stress-label">Elevator, the way in with a bike (street zoom)</span>
        </li>
        <li>
          <svg width="16" height="16" aria-hidden="true" className="rail-swatch">
            <circle cx="8" cy="8" r="4" fill="#6b7280" fillOpacity="0.7" stroke="#ffffff" strokeWidth="1" />
          </svg>
          <span className="stress-label">Stairs or escalator entrance (closer in)</span>
        </li>
      </ul>
      <p className="hint">{RAIL_HELP}</p>
    </>
  );
}
