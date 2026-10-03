/**
 * The route summary's list of stressful junctions (OWNER-DECISIONS item 172:
 * "Listed in the route summary, with a click explaining why"). A component of
 * its own so App.tsx only places it. A click on an item takes the map to the
 * junction and opens the same card the marker's click does.
 */
import type { RouteResponse } from "./lib/api.ts";
import {
  JUNCTION_HINT,
  junctionCounts,
  junctionHeadline,
  junctionItems,
  warningIconSvg,
} from "./lib/intersectionMarkers.ts";

interface Props {
  route: RouteResponse;
  onSelect: (index: number) => void;
}

export function IntersectionList({ route, onSelect }: Props) {
  // Null: the API could not read the junctions in time, or is older than the
  // model; there is nothing true to say, so nothing is said.
  if (route.intersections == null) return null;
  const items = junctionItems(route);
  const counts = junctionCounts(items);
  return (
    <figure className="junctions">
      <figcaption>{junctionHeadline(counts)}</figcaption>
      {items.length > 0 && (
        <>
          <ul className="junction-list" aria-label="Stressful junctions, in route order">
            {items.map((item) => (
              <li key={item.index}>
                <button
                  type="button"
                  className={`junction-item junction-${item.severity}`}
                  data-junction-index={item.index}
                  onClick={() => onSelect(item.index)}
                >
                  <span className="junction-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: warningIconSvg(item.severity, 18) }} />
                  <span className="junction-severity">{item.severityText}</span>
                  {/* Heard as "Higher stress, At (the distance): (the reason)". */}
                  <span className="visually-hidden">, </span>
                  <span className="junction-where">{item.where}</span>
                  <span className="visually-hidden">: </span>
                  <span className="junction-reason">{item.reason}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="hint">{JUNCTION_HINT}</p>
        </>
      )}
    </figure>
  );
}
