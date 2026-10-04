/**
 * The routes to choose from (OWNER-DECISIONS 265), a group of radio buttons: the
 * keys and the screen reader's own group announcements do the work, and nothing is
 * said as a colour. Only shown where there is more than one route. The route
 * chosen is drawn on the map and described below, and the choice is announced once
 * it has settled with the route's figures (App.tsx).
 *
 * Each radio's name is short - its rank, its distance and how that differs from
 * Route 1 - and its full figures are its description; the hint the group shares is
 * the fieldset's description, read once on entering the group rather than on every
 * arrow press (the a11y review's SF2). Written with createElement so a test renders it.
 */
import { createElement as h, useId, type ReactElement } from "react";
import { candidateRows, candidatesHint } from "./candidates.ts";
import type { RouteResponse } from "./api.ts";

interface Props {
  answer: RouteResponse | null;
  choice: number;
  onChoose: (index: number) => void;
}

export function CandidatePicker(props: Props): ReactElement | null {
  return candidateFieldset(useId(), props);
}

/** The picker's markup for the ids under `id` (CandidatePicker passes useId's), or null with one route. */
export function candidateFieldset(id: string, { answer, choice, onChoose }: Props): ReactElement | null {
  const rows = candidateRows(answer);
  if (rows === null) return null;
  const hintId = `${id}-hint`;
  return h(
    "fieldset",
    { className: "candidates", "aria-describedby": hintId },
    h("legend", null, "Routes to choose from"),
    h("p", { className: "hint", id: hintId }, candidatesHint(answer)),
    ...rows.map((row, index) =>
      h(
        "label",
        { key: index, className: "candidate" },
        h("input", {
          type: "radio",
          name: `${id}-candidate`,
          checked: choice === index,
          onChange: () => onChoose(index),
          "aria-labelledby": `${id}-name-${index}`,
          "aria-describedby": row.line ? `${id}-line-${index}` : undefined,
        }),
        h("span", { className: "candidate-name", id: `${id}-name-${index}` }, row.name),
        row.line ? h("span", { className: "candidate-line", id: `${id}-line-${index}` }, row.line) : null,
      ),
    ),
  );
}
