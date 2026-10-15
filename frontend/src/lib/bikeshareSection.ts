/**
 * The Layers sheet's bikeshare section (v0.7.0; lib/bikeshareDocks.ts): one switch per service, in a
 * LayerSection (lib/layerSection.ts). A service whose licence is not recorded is listed, switched off and
 * unavailable, with why in words. Plain createElement, so node --test renders it.
 */
import { createElement as h, useId, type ReactElement } from "react";
import { DOCKS_HINT, DOCKS_SECTION_TITLE, NOT_LICENSED, type OperatorInfo } from "./bikeshareDocks.ts";
import { LayerSection } from "./layerSection.ts";

export interface BikeshareSectionProps {
  operators: readonly OperatorInfo[];
  choices: Record<string, boolean>;
  onChange: (next: Record<string, boolean>) => void;
  status: string;
}

export function BikeshareSection({ operators, choices, onChange, status }: BikeshareSectionProps): ReactElement {
  const base = useId();
  const licensed = operators.filter((o) => o.licensed);
  return h(
    LayerSection,
    {
      id: "bikeshare",
      title: DOCKS_SECTION_TITLE,
      headingId: "bikeshare-heading",
      layers: licensed.map((o) => ({ key: o.id, label: o.name, on: choices[o.id] === true })),
      onLayers: (next: Record<string, boolean>) => onChange({ ...choices, ...next }),
      status,
    },
    ...operators.map((o) => {
      const whyId = `${base}-${o.id}-why`;
      return h(
        "div",
        { key: o.id, className: "bikeshare-operator" },
        h(
          "label",
          { className: "toggle" },
          h("input", {
            type: "checkbox",
            checked: o.licensed && choices[o.id] === true,
            disabled: !o.licensed,
            "aria-describedby": o.licensed ? undefined : whyId,
            onChange: (event: { target: { checked: boolean } }) => onChange({ ...choices, [o.id]: event.target.checked }),
          }),
          h("span", { className: "operator-swatch", style: { background: o.colour }, "aria-hidden": "true" }, o.initial),
          o.name,
        ),
        !o.licensed && h("p", { id: whyId, className: "hint" }, `${o.name}: ${NOT_LICENSED}.`),
      );
    }),
    h("p", { className: "hint" }, DOCKS_HINT),
  );
}
