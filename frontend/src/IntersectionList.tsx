/**
 * The route summary's list of stressful junctions (OWNER-DECISIONS item 172:
 * "Listed in the route summary, with a click explaining why"). A component of
 * its own so App.tsx only places it. A click on an item takes the map to the
 * junction and opens the same card the marker's click does.
 *
 * On a Mass Ride (OWNER-DECISIONS 233, 234) signalized crossings that run
 * within a quarter mile of one another are one row: a disclosure button
 * (aria-expanded, aria-controls) that opens onto its members, which are the
 * ordinary rows and open the ordinary card. Closed to begin with, nothing is
 * announced when it opens, and the focus stays on the button. Every crossing is
 * still a junction of its own on the map.
 */
import { useId, useState } from "react";
import type { RouteResponse } from "./lib/api.ts";
import {
  JUNCTION_HINT,
  type JunctionGroupItem,
  type JunctionItem,
  junctionCounts,
  junctionHeadline,
  junctionItems,
  junctionRows,
  rowName,
  warningIconSvg,
} from "./lib/intersectionMarkers.ts";
import { chevron } from "./lib/routeDescription.ts";
import { AVOID_SYMBOL, avoidItems, avoidRowName } from "./lib/avoidJunctions.ts";

interface Props {
  route: RouteResponse;
  onSelect: (index: number) => void;
}

function JunctionButton({ item, onSelect }: { item: JunctionItem; onSelect: (index: number) => void }) {
  return (
    <button
      type="button"
      className={`junction-item junction-${item.severity}`}
      data-junction-index={item.index}
      aria-label={rowName(item.severityText, item.where, item.reason)}
      onClick={() => onSelect(item.index)}
    >
      <span className="junction-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: warningIconSvg(item.severity, 18) }} />
      <span className="junction-severity">{item.severityText}</span>
      <span className="junction-where">{item.where}</span>
      <span className="junction-reason">{item.reason}</span>
    </button>
  );
}

/** A group of signalized crossings: one row that opens onto its crossings. */
function JunctionGroupRow({ group, onSelect }: { group: JunctionGroupItem; onSelect: (index: number) => void }) {
  const [open, setOpen] = useState(false);
  const listId = useId();
  return (
    <li className="junction-group-row">
      <button
        type="button"
        className={`junction-item junction-group-toggle junction-${group.severity}`}
        data-junction-group={group.number}
        aria-expanded={open}
        aria-controls={listId}
        aria-label={rowName(group.severityText, "Group", group.text)}
        onClick={() => setOpen(!open)}
      >
        <span className="junction-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: warningIconSvg(group.severity, 18) }} />
        <span className="junction-severity">{group.severityText}</span>
        <span className="junction-where">
          <span aria-hidden="true">{chevron(open)} </span>Group
        </span>
        <span className="junction-reason">{group.text}</span>
      </button>
      <ul id={listId} className="junction-members" aria-label="Crossings in this group, in route order" hidden={!open}>
        {group.members.map((item) => (
          <li key={item.index}>
            <JunctionButton item={item} onSelect={onSelect} />
          </li>
        ))}
      </ul>
    </li>
  );
}

/**
 * The Avoid-rated junctions the route passes (OWNER-DECISIONS 307-310), first: rated by
 * a person, and the worst there is. The symbol is seen, not heard; each row's name is
 * the rating and the reason (309).
 */
export function AvoidJunctionList({ route }: { route: RouteResponse }) {
  const avoid = avoidItems(route);
  if (avoid.length === 0) return null;
  return (
    <ul className="junction-list avoid-list" aria-label="Avoid-rated junctions, in route order">
      {avoid.map((item, i) => (
        <li key={`${item.id}-${i}`} className="junction-avoid">
          <span className="avoid-symbol" aria-hidden="true">
            {AVOID_SYMBOL}
          </span>{" "}
          {/* One string, read as written: the rating, the junction, the reason, where. */}
          <span className="junction-reason">{avoidRowName(item)}</span>
        </li>
      ))}
    </ul>
  );
}

export function IntersectionList({ route, onSelect }: Props) {
  // Null: the API could not read the junctions in time, or is older than the
  // model; there is nothing true to say, so nothing is said (the Avoid-rated
  // junctions, which come from the route's line, are said all the same).
  if (route.intersections == null) return <AvoidJunctionList route={route} />;
  const items = junctionItems(route);
  const counts = junctionCounts(items);
  const rows = junctionRows(route);
  return (
    <figure className="junctions">
      <figcaption>{junctionHeadline(counts)}</figcaption>
      <AvoidJunctionList route={route} />
      {items.length > 0 && (
        <>
          <ul className="junction-list" aria-label="Stressful junctions, in route order">
            {rows.map((row) =>
              row.kind === "group" ? (
                <JunctionGroupRow key={`g${row.group.number}-${row.group.members[0].m}`} group={row.group} onSelect={onSelect} />
              ) : (
                <li key={row.item.index}>
                  <JunctionButton item={row.item} onSelect={onSelect} />
                </li>
              ),
            )}
          </ul>
          <p className="hint">{JUNCTION_HINT}</p>
        </>
      )}
    </figure>
  );
}
