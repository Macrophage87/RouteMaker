/**
 * The routes to choose from (OWNER-DECISIONS 265), a group of radio buttons: the
 * keys and the screen reader's own group announcements do the work, and nothing is
 * said as a colour. Only shown where there is more than one route. The route
 * chosen is drawn on the map and described below, and the choice is announced once
 * it has settled with the route's figures (App.tsx).
 */
import { useId } from "react";
import { candidateRows } from "./lib/candidates.ts";
import type { RouteResponse } from "./lib/api.ts";

interface Props {
  answer: RouteResponse | null;
  choice: number;
  onChoose: (index: number) => void;
}

export function CandidatePicker({ answer, choice, onChoose }: Props) {
  const id = useId();
  const rows = candidateRows(answer);
  if (rows === null) return null;
  return (
    <fieldset className="candidates">
      <legend>Routes to choose from</legend>
      <p className="hint" id={`${id}-hint`}>
        Each is within your longest ride and about as calm as the first. The map shows the one chosen: pick by the
        scenery you see there.
      </p>
      {rows.map((row, index) => (
        <label key={row.name} className="candidate">
          <input
            type="radio"
            name={`${id}-candidate`}
            checked={choice === index}
            onChange={() => onChoose(index)}
            aria-describedby={`${id}-hint`}
          />
          <span className="candidate-name">{row.name}</span>
          <span className="candidate-line">{row.line}</span>
        </label>
      ))}
    </fieldset>
  );
}
