/**
 * The route summary's list of stressful junctions (OWNER-DECISIONS item 172:
 * "Listed in the route summary, with a click explaining why"). A component of
 * its own so App.tsx only places it. A click on an item takes the map to the
 * junction and opens the same card the marker's click does.
 *
 * On a Mass Ride (OWNER-DECISIONS 233, 234) signalised crossings that run
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
  warningIconSvg,
} from "./lib/intersectionMarkers.ts";
import { chevron } from "./lib/routeDescription.ts";

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
  );
}

/** A group of signalised crossings: one row that opens onto its crossings. */
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
        onClick={() => setOpen(!open)}
      >
        <span className="junction-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: warningIconSvg(group.severity, 18) }} />
        <span className="junction-severity">{group.severityText}</span>
        <span className="visually-hidden">, </span>
        <span className="junction-where">
          <span aria-hidden="true">{chevron(open)} </span>Group
        </span>
        <span className="visually-hidden">: </span>
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

export function IntersectionList({ route, onSelect }: Props) {
  // Null: the API could not read the junctions in time, or is older than the
  // model; there is nothing true to say, so nothing is said.
  if (route.intersections == null) return null;
  const items = junctionItems(route);
  const counts = junctionCounts(items);
  const rows = junctionRows(route);
  return (
    <figure className="junctions">
      <figcaption>{junctionHeadline(counts)}</figcaption>
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
