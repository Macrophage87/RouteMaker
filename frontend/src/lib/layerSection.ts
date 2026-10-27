/**
 * One section of the Layers sheet (the owner, 2026-10-12: "For layers, let's make it less wordy. Maybe have a
 * general off and on for each section, then let it expand."). Each section is one row: its name, one switch
 * for the whole section and a disclosure button; its layers' own switches, any extra control a layer has
 * (the Climbs layer's "Show climbs from") and their one-line hints are inside, closed to begin with.
 *
 * The section switch: On turns on the layers the rider last had on in it (else every layer in it); Off hides
 * them all and remembers which were on (kept on this device, LAYER_SECTIONS_KEY). With some but not all on it
 * shows On, its state says "Some on" in words, and its description names the ones that are. A section of one
 * layer has no memory to keep: its switch is that layer's switch.
 *
 * The keyboard order is the row's: the section switch, the disclosure, then the layers. A button with
 * role="switch" like the layers' own switches, its name the section's heading. Written with createElement so
 * a test renders it.
 */
import { createElement as h, useState, type ReactElement, type ReactNode } from "react";
import { t } from "./i18n.ts";
import { ICON_PATHS } from "./iconPaths.ts";

export const LAYER_SECTIONS_KEY = "routemaker.layerSections";

export type SectionState = "on" | "off" | "some";

export interface SectionLayer {
  /** A short stable key, kept in the section's memory. */
  key: string;
  /** The layer's name, as its own switch says it. */
  label: string;
  on: boolean;
}

/** On, off, or some on: from the section's layers. */
export function sectionState(layers: readonly SectionLayer[]): SectionState {
  const on = layers.filter((layer) => layer.on).length;
  return on === 0 ? "off" : on === layers.length ? "on" : "some";
}

/** The words of the section switch's state, shown beside it (not colour alone). */
export const SECTION_STATE_WORDS: Record<SectionState, string> = { on: t("On"), off: t("Off"), some: t("Some on") };

/** The switch's description while some are on: "Some on: Metro." */
export function someOnText(layers: readonly SectionLayer[]): string {
  return t("Some on: {layers}.", { layers: layers.filter((layer) => layer.on).map((layer) => layer.label).join(", ") });
}

type Memory = Record<string, string[]>;
type Store = Pick<Storage, "getItem" | "setItem">;

function storage(): Store | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Each section's remembered layers; anything this page did not write is ignored. */
export function readSectionMemory(store: Store | null = storage()): Memory {
  try {
    const parsed: unknown = JSON.parse(store?.getItem(LAYER_SECTIONS_KEY) ?? "{}");
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const memory: Memory = {};
    for (const [id, keys] of Object.entries(parsed as Record<string, unknown>)) {
      if (Array.isArray(keys) && keys.every((key) => typeof key === "string")) memory[id] = keys;
    }
    return memory;
  } catch {
    return {};
  }
}

function rememberSection(id: string, keys: string[], store: Store | null): void {
  try {
    store?.setItem(LAYER_SECTIONS_KEY, JSON.stringify({ ...readSectionMemory(store), [id]: keys }));
  } catch {
    // Private mode or full: the section still works, it just forgets.
  }
}

/**
 * What a press of the section switch turns each layer to. Off (from on or some on) turns every layer off and
 * remembers the ones that were on; On turns on the remembered ones that are still in the section, else all.
 */
export function sectionPress(id: string, layers: readonly SectionLayer[], store: Store | null = storage()): Record<string, boolean> {
  const next: Record<string, boolean> = {};
  if (sectionState(layers) !== "off") {
    if (layers.length > 1) rememberSection(id, layers.filter((layer) => layer.on).map((layer) => layer.key), store);
    for (const layer of layers) next[layer.key] = false;
    return next;
  }
  const kept = (readSectionMemory(store)[id] ?? []).filter((key) => layers.some((layer) => layer.key === key));
  const turnOn = kept.length > 0 ? kept : layers.map((layer) => layer.key);
  for (const layer of layers) next[layer.key] = turnOn.includes(layer.key);
  return next;
}

export interface LayerSectionProps {
  /** The section's id: its elements' ids start with it, and its memory is kept under it. */
  id: string;
  title: string;
  /** The heading's id, where tests and older links look for it (layers-heading, water-heading, ...). */
  headingId?: string;
  /** The section switch's id; defaults to `${id}-section-switch`. */
  switchId?: string;
  className?: string;
  /** The section's layers. None (the stress map unavailable): no switch, the row is its name and the disclosure. */
  layers: readonly SectionLayer[];
  /** Turn each layer to its new state (sectionPress's answer). */
  onLayers: (next: Record<string, boolean>) => void;
  /**
   * One status line under the row, a persistent role="status" whose words change (the a11y review's N8):
   * loading or unavailable, said whether the section is open or closed. A function gets whether it is open,
   * for a section whose layers keep their own status lines inside.
   */
  status?: string | ((open: boolean) => string);
  children?: ReactNode;
}

/** The section: its row (name, switch, disclosure), its status line, and its layers, closed to begin with. */
export function LayerSection({ id, title, headingId = `${id}-heading`, switchId = `${id}-section-switch`, className, layers, onLayers, status, children }: LayerSectionProps): ReactElement {
  const [open, setOpen] = useState(false);
  const state = sectionState(layers);
  const bodyId = `${id}-section-body`;
  const someId = `${id}-section-some`;
  const said = typeof status === "function" ? status(open) : status;
  return h(
    "section",
    { "aria-labelledby": headingId, className: ["layer-group", "layer-section", className].filter(Boolean).join(" ") },
    h(
      "div",
      { className: "layer-section-row" },
      h("h3", { id: headingId }, title),
      layers.length > 0 &&
        h(
          "button",
          {
            type: "button",
            role: "switch",
            id: switchId,
            className: "switch section-switch",
            "aria-checked": state !== "off",
            "aria-labelledby": headingId,
            "aria-describedby": state === "some" ? someId : undefined,
            onClick: () => onLayers(sectionPress(id, layers)),
          },
          h("span", { className: "switch-state", "aria-hidden": "true" }, SECTION_STATE_WORDS[state]),
        ),
      h(
        "button",
        {
          type: "button",
          className: "section-chevron",
          "aria-expanded": open,
          "aria-controls": bodyId,
          "aria-label": t("{title} layers", { title }),
          onClick: () => setOpen(!open),
        },
        h("svg", {
          className: "icon",
          width: 20,
          height: 20,
          viewBox: "0 0 24 24",
          fill: "none",
          stroke: "currentColor",
          strokeWidth: 2,
          strokeLinecap: "round",
          strokeLinejoin: "round",
          "aria-hidden": "true",
          focusable: "false",
          dangerouslySetInnerHTML: { __html: ICON_PATHS.down },
        }),
      ),
    ),
    state === "some" && h("span", { id: someId, className: "visually-hidden" }, someOnText(layers)),
    status !== undefined && h("p", { className: "hint layer-section-status", role: "status" }, said),
    h("div", { id: bodyId, className: "layer-section-body", hidden: !open }, children),
  );
}
