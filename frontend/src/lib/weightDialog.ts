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
import {
  BLANK,
  WEIGHT_DIALOG_TITLE,
  WEIGHT_PURPOSE,
  WEIGHT_ROUGH,
  editPart,
  editTotal,
  formatLbKg,
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
  if (kg === undefined) return `Total: nothing entered; the defaults, ${formatLbKg(split.riderKg + split.bikeKg + split.cargoKg)}, are used.`;
  if (kg === null) return "Total: not a number yet.";
  return `Total: ${formatLbKg(kg)}.`;
}

// Labelled pounds first and kilograms in brackets (316); the kilograms a typed figure comes to are
// part of the field's description, so a screen reader hears them too.
export const WEIGHT_LABELS = { rider: "Rider, lb (kg)", bike: "Bike, lb (kg)", cargo: "Cargo, lb (kg)", total: "Total, lb (kg)" } as const;

const PARTS = [
  { key: "rider", label: WEIGHT_LABELS.rider, kg: "riderKg" },
  { key: "bike", label: WEIGHT_LABELS.bike, kg: "bikeKg" },
  { key: "cargo", label: WEIGHT_LABELS.cargo, kg: "cargoKg" },
] as const;

interface DialogProps {
  open: boolean;
  /** What is kept, or null: only its date is ever shown. */
  saved: StoredWeight | null;
  /** Whether this browser keeps it (the checkbox starts so). */
  remembered: boolean;
  split: Split;
  onSave: (weight: StoredWeight, remember: boolean) => void;
  onClear: () => void;
  onClose: () => void;
  /** For a test: the clock. */
  now?: () => number;
}

/** The dialog's markup for the ids under `id`, with this worksheet (WeightDialog keeps the state). */
export function weightDialogBody(
  id: string,
  props: DialogProps,
  state: { sheet: Worksheet; remember: boolean; refused: string; said?: string },
  set: { sheet: (s: Worksheet) => void; remember: (on: boolean) => void; refused: (text: string) => void },
): Array<ReactElement | null> {
  const { sheet, remember, refused } = state;
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
    props.onSave(stored, remember);
  };
  const cancel = () => {
    blank();
    props.onClose();
  };
  const field = (key: string, label: string, value: string, hint: string, onChange: (text: string) => void) => {
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
        value,
        "aria-describedby": `${id}-${key}-kg ${id}-${key}-hint${invalid ? ` ${id}-rule` : ""}`,
        "aria-invalid": invalid ? "true" : undefined,
        onChange: (event: { target: { value: string } }) => onChange(event.target.value),
      }),
      h("span", { className: "weight-kg", id: `${id}-${key}-kg` }, typeof kg === "number" ? `(${kg.toFixed(1)} kg)` : ""),
      h("p", { className: "hint", id: `${id}-${key}-hint` }, hint),
    );
  };
  return [
    h("h2", { key: "t", id: `${id}-title` }, WEIGHT_DIALOG_TITLE),
    h("p", { key: "d1", id: `${id}-purpose` }, WEIGHT_PURPOSE),
    h("p", { key: "d2", id: `${id}-rough` }, WEIGHT_ROUGH),
    props.saved ? h("p", { key: "s", className: "notice", id: `${id}-saved` }, savedNotice(props.saved, now())) : null,
    ...PARTS.map((part) =>
      field(part.key, part.label, sheet[part.key], `Blank: ${formatLbKg(props.split[part.kg])}.`, (text) => set.sheet(editPart(sheet, part.key, text, props.split))),
    ),
    field("total", WEIGHT_LABELS.total, sheet.total, "Or type the total alone: it replaces the parts.", (text) => set.sheet(editTotal(text))),
    h("p", { key: "sum", className: "weight-total", role: "status", "aria-live": "polite" }, state.said ?? totalSaid(sheet, props.split)),
    h(
      "label",
      { key: "r", className: "toggle" },
      h("input", { type: "checkbox", checked: remember, onChange: (event: { target: { checked: boolean } }) => set.remember(event.target.checked) }),
      "Remember on this device",
    ),
    h("p", { key: "rule", id: `${id}-rule`, className: refused ? "notice dial-rule" : "dial-rule", "aria-live": "assertive" }, refused),
    h(
      "div",
      { key: "b", className: "actions" },
      h("button", { type: "button", onClick: save }, "Save"),
      props.saved ? h("button", { type: "button", className: "secondary", onClick: () => props.onClear() }, "Clear") : null,
      h("button", { type: "button", className: "secondary", onClick: cancel }, "Cancel"),
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

/** What every open starts from: blank fields (317(b)), no refusal, and the checkbox as this browser has it. */
export function openedState(props: Pick<DialogProps, "remembered" | "saved">): { sheet: Worksheet; remember: boolean; refused: string } {
  return { sheet: BLANK, remember: props.remembered, refused: "" };
}

export function WeightDialog(props: DialogProps): ReactElement {
  const id = useId();
  const ref = useRef<HTMLDialogElement>(null);
  const [sheet, setSheet] = useState<Worksheet>(BLANK);
  const [remember, setRemember] = useState(props.remembered);
  const [refused, setRefused] = useState("");
  // The polite total, a moment behind the typing (TOTAL_SAID_DELAY_MS).
  const live = totalSaid(sheet, props.split);
  const [said, setSaid] = useState(live);
  useEffect(() => {
    const timer = setTimeout(() => setSaid(live), TOTAL_SAID_DELAY_MS);
    return () => clearTimeout(timer);
  }, [live]);
  // Every open starts blank (317(b)), and the checkbox as this browser has it.
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (props.open) {
      const start = openedState(props);
      setSheet(start.sheet);
      setRefused(start.refused);
      setRemember(start.remember);
      if (!dialog.open) dialog.showModal?.();
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
    ...weightDialogBody(id, props, { sheet, remember, refused, said }, { sheet: setSheet, remember: setRemember, refused: setRefused }),
  );
}

/** The ride panel's part: the line, never the number, and Change, which opens the dialog. */
export function WeightSetting(props: {
  saved: StoredWeight | null;
  remembered: boolean;
  split: Split;
  onSave: (weight: StoredWeight, remember: boolean) => void;
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
      { type: "button", ref: change, className: "secondary", "aria-label": "Change rider and bike weight", "aria-describedby": `${id}-line`, onClick: () => setOpen(true) },
      "Change",
    ),
    h(WeightDialog, {
      open,
      saved: props.saved,
      remembered: props.remembered,
      split: props.split,
      now: props.now,
      onSave: (weight, remember) => {
        props.onSave(weight, remember);
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
