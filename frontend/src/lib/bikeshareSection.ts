/**
 * The Layers sheet's bikeshare section (v0.7.0; lib/bikeshareDocks.ts), a LayerSection (lib/layerSection.ts).
 * Capital Bikeshare is the only service (Lime and Veo were left out, the owner 2026-10-15), so the section's
 * switch is its switch, and inside is only the hint. Should the server name a second licensed service, each
 * gets a switch of its own inside. Plain createElement, so node --test renders it.
 */
import { createElement as h, type ReactElement } from "react";
import { DOCKS_HINT, DOCKS_SECTION_TITLE, type OperatorInfo } from "./bikeshareDocks.ts";
import { LayerSection } from "./layerSection.ts";

export interface BikeshareSectionProps {
  operators: readonly OperatorInfo[];
  choices: Record<string, boolean>;
  onChange: (next: Record<string, boolean>) => void;
  status: string;
}

export function BikeshareSection({ operators, choices, onChange, status }: BikeshareSectionProps): ReactElement {
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
    // One service: the section switch above is its switch, so no list of one.
    ...(licensed.length > 1
      ? licensed.map((o) =>
          h(
            "div",
            { key: o.id, className: "bikeshare-operator" },
            h(
              "label",
              { className: "toggle" },
              h("input", {
                type: "checkbox",
                checked: choices[o.id] === true,
                onChange: (event: { target: { checked: boolean } }) => onChange({ ...choices, [o.id]: event.target.checked }),
              }),
              h("span", { className: "operator-swatch", style: { background: o.colour }, "aria-hidden": "true" }, o.initial),
              o.name,
            ),
          ),
        )
      : []),
    h("p", { className: "hint" }, DOCKS_HINT),
  );
}
