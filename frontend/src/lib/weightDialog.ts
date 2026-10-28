/**
 * The rider and bike weight's dialog and the ride panel's line (OWNER-DECISIONS
 * 313-318; lib/weight.ts has the rules). A native <dialog> opened with showModal: it
 * is modal (the page behind is inert), Escape closes it, and the focus moves into it;
 * on close the focus goes back to the Change button (DialsPanel). Labelled by its
 * heading and described by the two lines it leads with (318).
 *
 * Every open starts blank (317(b)): a saved weight is said to exist, with its date,
 * and its numbers are never put in a field or anywhere else. Written with
 * createElement so a test renders it.
 */
import { createElement as h, useEffect, useId, useRef, useState, type ReactElement, type RefObject } from "react";
import { t } from "./i18n.ts";
import {
  BLANK,
  WEIGHT_DIALOG_TITLE,
  WEIGHT_PURPOSE,
  WEIGHT_ROUGH,
  editPart,
  editTotal,
  formatLbKg,
  lbOf,
  poundsToKg,
  savedNotice,
  toStored,
  weightLine,
  worksheetKg,
  type Split,
  type StoredWeight,
  type Worksheet,
} from "./weight.ts";

/**
 * How long the polite total waits after the last keystroke before it changes (the
 * re-check's N-A): typing 180 said "34 lb", "51 lb", then "213 lb" over the key echo.
 */
export const TOTAL_SAID_DELAY_MS = 700;

/** The polite total under the worksheet, from what is entered; the defaults with nothing entered. */
export function totalSaid(sheet: Worksheet, split: Split): string {
  const kg = worksheetKg(sheet, split);
  if (kg === undefined) return t("Total: default, {weight}.", { weight: formatLbKg(split.riderKg + split.bikeKg + split.cargoKg) });
  if (kg === null) return t("Total: not a number yet.");
  return t("Total: {weight}.", { weight: formatLbKg(kg) });
}

// Labelled pounds first and kilograms in brackets (316); the kilograms a typed figure comes to are
// part of the field's description, so a screen reader hears them too.
export const WEIGHT_LABELS = { rider: t("Rider, lb (kg)"), bike: t("Bike, lb (kg)"), cargo: t("Cargo, lb (kg)"), total: t("Total, lb (kg)") } as const;

const PARTS = [
  { key: "rider", label: WEIGHT_LABELS.rider, kg: "riderKg" },
  { key: "bike", label: WEIGHT_LABELS.bike, kg: "bikeKg" },
  { key: "cargo", label: WEIGHT_LABELS.cargo, kg: "cargoKg" },
] as const;

interface DialogProps {
  open: boolean;
  /** What is kept, or null: only its date is ever shown. */
  saved: StoredWeight | null;
  split: Split;
  onSave: (weight: StoredWeight) => void;
  onClear: () => void;
  onClose: () => void;
  /** For a test: the clock. */
  now?: () => number;
}

/** The dialog's markup for the ids under `id`, with this worksheet (WeightDialog keeps the state). */
export function weightDialogBody(
  id: string,
  props: DialogProps,
  state: { sheet: Worksheet; refused: string; said?: string },
  set: { sheet: (s: Worksheet) => void; refused: (text: string) => void },
): Array<ReactElement | null> {
  const { sheet, refused } = state;
  const now = props.now ?? Date.now;
  // Whatever closes the dialog leaves it blank, so no figure typed stays in the page (the
  // review's S2; 313, 317(b)): a closed <dialog> is still in the DOM.
  const blank = () => {
    set.sheet(BLANK);
    set.refused("");
  };
  const save = () => {
    const stored = toStored(sheet, props.split, now());
    if ("refused" in stored) {
      set.refused(stored.refused);
      return;
    }
    // Outside the range it is the nearer limit, silently (352).
    blank();
    props.onSave(stored);
  };
  const cancel = () => {
    blank();
    props.onClose();
  };
  // A part's hint is for a screen reader; on screen its default is its placeholder, so each part is one row.
  // The Total's hint stays on screen: it says what typing a total does.
  const field = (key: string, label: string, value: string, hint: string, placeholder: string | undefined, onChange: (text: string) => void) => {
    const kg = poundsToKg(value);
    // A refused entry marks the field that is not a number, and points it at the rule (N-C).
    const invalid = refused !== "" && kg === null;
    return h(
      "div",
      { key, className: "weight-field" },
      h("label", { htmlFor: `${id}-${key}` }, label),
      h("input", {
        id: `${id}-${key}`,
        type: "text",
        inputMode: "decimal",
        autoComplete: "off",
        placeholder,
        value,
        "aria-describedby": `${id}-${key}-kg ${id}-${key}-hint${invalid ? ` ${id}-rule` : ""}`,
        "aria-invalid": invalid ? "true" : undefined,
        onChange: (event: { target: { value: string } }) => onChange(event.target.value),
      }),
      h("span", { className: "weight-kg", id: `${id}-${key}-kg` }, typeof kg === "number" ? `(${kg.toFixed(1)} kg)` : ""),
      h("p", { className: placeholder === undefined ? "hint" : "hint visually-hidden", id: `${id}-${key}-hint` }, hint),
    );
  };
  return [
    h("h2", { key: "t", id: `${id}-title`, tabIndex: -1 }, WEIGHT_DIALOG_TITLE),
    h("p", { key: "d1", id: `${id}-purpose` }, WEIGHT_PURPOSE),
    h("p", { key: "d2", id: `${id}-rough` }, WEIGHT_ROUGH),
    props.saved ? h("p", { key: "s", className: "notice", id: `${id}-saved` }, savedNotice(props.saved, now())) : null,
    ...PARTS.map((part) =>
      field(part.key, part.label, sheet[part.key], t("Blank: {weight}.", { weight: formatLbKg(props.split[part.kg]) }), String(lbOf(props.split[part.kg])), (text) => set.sheet(editPart(sheet, part.key, text, props.split))),
    ),
    field("total", WEIGHT_LABELS.total, sheet.total, t("Or the total alone."), undefined, (text) => set.sheet(editTotal(text))),
    h("p", { key: "sum", className: "weight-total", role: "status", "aria-live": "polite" }, state.said ?? totalSaid(sheet, props.split)),
    h("p", { key: "rule", id: `${id}-rule`, className: refused ? "notice dial-rule" : "dial-rule", "aria-live": "assertive" }, refused),
    h(
      "div",
      { key: "b", className: "actions" },
      h("button", { type: "button", onClick: save }, t("Save")),
      props.saved ? h("button", { type: "button", className: "secondary", onClick: () => props.onClear() }, t("Clear")) : null,
      h("button", { type: "button", className: "secondary", onClick: cancel }, t("Cancel")),
    ),
  ];
}

/**
 * What every close leaves (Save, Cancel, Clear, Escape: each ends with the dialog closed):
 * blank fields and no refusal, so no figure typed stays in the closed <dialog>, which is
 * still in the DOM (313, 317(b); the re-check's S2, and the mutation re-check's SF3).
 */
export function closedState(): { sheet: Worksheet; refused: string } {
  return { sheet: BLANK, refused: "" };
}

/** What every open starts from: blank fields (317(b)) and no refusal. */
export function openedState(): { sheet: Worksheet; refused: string } {
  return { sheet: BLANK, refused: "" };
}

export function WeightDialog(props: DialogProps): ReactElement {
  const id = useId();
  const ref = useRef<HTMLDialogElement>(null);
  const [sheet, setSheet] = useState<Worksheet>(BLANK);
  const [refused, setRefused] = useState("");
  // The polite total, a moment behind the typing (TOTAL_SAID_DELAY_MS).
  const live = totalSaid(sheet, props.split);
  const [said, setSaid] = useState(live);
  useEffect(() => {
    const timer = setTimeout(() => setSaid(live), TOTAL_SAID_DELAY_MS);
    return () => clearTimeout(timer);
  }, [live]);
  // Every open starts blank (317(b)).
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (props.open) {
      const start = openedState();
      setSheet(start.sheet);
      setRefused(start.refused);
      if (!dialog.open) {
        dialog.showModal?.();
        // The focus starts on the heading, not the first box (showModal's own choice): a box would open a phone's
        // keyboard, which resizes the page and leaves the sheet behind scrolled when it closes (Stephen 2026-10-19:
        // "opening a dialog often causes the text to shift"). The heading is read first, then Tab goes to Rider.
        dialog.querySelector<HTMLElement>("h2")?.focus();
      }
    } else {
      // Closed (Save, Cancel, Clear, Escape): blank, so nothing typed stays in the page (S2).
      const end = closedState();
      setSheet(end.sheet);
      setRefused(end.refused);
      if (dialog.open) dialog.close();
    }
  }, [props.open]);
  return h(
    "dialog",
    {
      ref,
      className: "weight-dialog",
      "aria-modal": "true",
      "aria-labelledby": `${id}-title`,
      "aria-describedby": `${id}-purpose ${id}-rough`,
      // Escape, or the dialog closed any other way: the panel's state follows.
      onClose: () => props.onClose(),
      onCancel: () => props.onClose(),
    },
    ...weightDialogBody(id, props, { sheet, refused, said }, { sheet: setSheet, refused: setRefused }),
  );
}

/** The ride panel's part: the line, never the number, and Change, which opens the dialog. */
export function WeightSetting(props: {
  saved: StoredWeight | null;
  split: Split;
  onSave: (weight: StoredWeight) => void;
  onClear: () => void;
  now?: () => number;
}): ReactElement {
  const id = useId();
  const [open, setOpen] = useState(false);
  const change = useRef<HTMLButtonElement>(null);
  const close = () => {
    setOpen(false);
    // Back to where the rider was (the dialog's own return of focus is not in every browser).
    (change as RefObject<HTMLButtonElement>).current?.focus();
  };
  return h(
    "div",
    { className: "dial weight-setting" },
    h("p", { className: "weight-line", id: `${id}-line` }, weightLine(props.saved, (props.now ?? Date.now)())),
    h(
      "button",
      { type: "button", ref: change, className: "secondary", "aria-label": t("Change rider and bike weight"), "aria-describedby": `${id}-line`, onClick: () => setOpen(true) },
      t("Change"),
    ),
    h(WeightDialog, {
      open,
      saved: props.saved,
      split: props.split,
      now: props.now,
      onSave: (weight) => {
        props.onSave(weight);
        close();
      },
      onClear: () => {
        props.onClear();
        close();
      },
      onClose: close,
    }),
  );
}
