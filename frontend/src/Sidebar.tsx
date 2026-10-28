/**
 * The sidebar redesign's small parts (OWNER-DECISIONS 312, mockup v3): the
 * "More tips" toggle, the quick figures, the bottom bar and the sheet it opens;
 * and, from lib/sidebarParts.ts, the Ride line, the folds (native <details>) of
 * the route summary and the legend's junctions. Kept out of App.tsx, which
 * places them.
 *
 * Every one is a real button or a real <details>, 44 px high at least, with its
 * state in aria-expanded (or the element's own) and its words in text; none
 * depends on colour. A sheet takes the focus to its heading when it opens, and
 * the Back button (or Escape) takes it back to the bar button that opened it.
 */
import { Fragment, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { BACK_LABEL, BAR_ITEMS, BAR_NAME, POPUP_CLOSE, POPUP_FOCUSABLE, barCurrent, listenForPopupSay, popupBackLabel, popupTabWrap, sheetEscape, type BarItem, type PanelView } from "./lib/sidebar.ts";
import { useNarrow } from "./app/hooks.ts";
import { Icon } from "./Icon.tsx";
import type { IconName } from "./lib/iconPaths.ts";
import type { QuickFigure } from "./lib/quickFigures.ts";

// The parts a test renders are written with createElement in lib/sidebarParts.ts (node's test runner
// reads .ts, not .tsx); App.tsx takes them from here with the rest.
export { HighContrastShortcut, Fold, JunctionLegend, PlannerZoomNotice, RideSettings } from "./lib/sidebarParts.ts";

/** The four quick figures: a label and a figure each, as a description list. */
export function QuickFigures({ figures }: { figures: readonly QuickFigure[] }) {
  return (
    <dl className="quick-figures">
      {figures.map((figure) => (
        <div key={figure.key} className={`quick-figure quick-${figure.key}`}>
          <dt>{figure.label}</dt>
          <dd>{figure.value}</dd>
        </div>
      ))}
    </dl>
  );
}

const ICONS: Record<BarItem["id"], IconName> = {
  plan: "list",
  layers: "layers",
  suggest: "flag",
  gpx: "file",
  settings: "gear",
};

/** The bottom bar: real buttons, each with an icon (hidden from screen readers) and its words. */
export function BottomBar({
  view,
  onOpen,
  buttonRef,
}: {
  view: PanelView;
  onOpen: (item: BarItem, button: HTMLButtonElement) => void;
  buttonRef: (id: BarItem["id"], button: HTMLButtonElement | null) => void;
}) {
  return (
    <nav aria-label={BAR_NAME} className="bottom-bar">
      {BAR_ITEMS.map((item) => {
        const current = barCurrent(item, view);
        return (
          <Fragment key={item.id}>
            <button
              id={`bar-${item.id}`}
              type="button"
              ref={(button) => buttonRef(item.id, button)}
              className="bar-button"
              aria-current={current ? "true" : undefined}
              aria-describedby={`bar-${item.id}-hint`}
              onClick={(event) => onOpen(item, event.currentTarget)}
            >
              <Icon name={ICONS[item.id]} />
              <span>{item.label}</span>
            </button>
            {/* The hint is a sibling, not part of the button, so the name is the label alone and the hint is
                heard once, as the description. `hidden` keeps it off the screen and out of the reading order, and
                aria-describedby still reads it. */}
            <span id={`bar-${item.id}-hint`} hidden>
              {item.description}
            </span>
          </Fragment>
        );
      })}
    </nav>
  );
}

/**
 * One of the bottom bar's sheets: a header with a Back button and a heading,
 * over its content. It stays in the page when hidden, so what it holds (the
 * opened GPX file, the switches) keeps its state.
 *
 * A popup sheet (lib/sidebar.ts POPUP_VIEWS; the owner, 2026-10-28) is the platform's <dialog>: on a phone it is
 * opened with showModal(), one screen high at most over the map, the page behind it inert, its title and Close at
 * the top; on a computer it is shown in the panel (show()), the side panel it always was. The same element either
 * way, so a rotated tablet keeps what the sheet holds.
 */
export function SheetFrame({
  id,
  title,
  open,
  onBack,
  headingRef,
  backLabel = BACK_LABEL,
  extra,
  popup = false,
  children,
}: {
  id: string;
  title: string;
  open: boolean;
  onBack: () => void;
  headingRef?: Ref<HTMLHeadingElement>;
  /** The Back button's words: back to the planner, or to the sheet this one was opened from. */
  backLabel?: string;
  /** A control at the header's end. */
  extra?: ReactNode;
  /** A popup on a phone, the side panel on a computer. */
  popup?: boolean;
  children: ReactNode;
}) {
  const narrow = useNarrow();
  const modal = popup && narrow;
  const dialogRef = useRef<HTMLDialogElement>(null);
  // Opened, closed, or moved between popup and panel, before the app's own effects move the focus into it or back.
  useLayoutEffect(() => {
    const dialog = dialogRef.current;
    if (!popup || !dialog) return;
    const want = !open ? "closed" : modal ? "modal" : "panel";
    const now = !dialog.open ? "closed" : dialog.matches(":modal") ? "modal" : "panel";
    if (want === now) return;
    if (dialog.open) dialog.close();
    if (want === "modal") dialog.showModal?.();
    else if (want === "panel") dialog.show?.();
  }, [popup, open, modal]);
  // The app's own words, said again in the popup while it is open (the page behind it is inert).
  const [said, setSaid] = useState({ text: "", count: 0 });
  useEffect(() => {
    if (!(modal && open)) return;
    const stop = listenForPopupSay((text) => setSaid((s) => ({ text, count: s.count + 1 })));
    return () => {
      stop();
      setSaid({ text: "", count: 0 });
    };
  }, [modal, open]);
  // Escape inside a nested dialog or the place search's list is theirs, not the sheet's (lib/sidebar.ts).
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    sheetEscape({ key: event.key, defaultPrevented: event.defaultPrevented, target: event.target as HTMLElement, preventDefault: () => event.preventDefault() }, onBack, dialogRef.current);
    // Tab is held inside the popup, as the ride type dialog holds it: past the last control to the first (Shift+Tab
    // the other way), not out to the browser's own; between them, the browser's order.
    const dialog = dialogRef.current;
    if (!modal || event.key !== "Tab" || event.defaultPrevented || !dialog || (event.target as HTMLElement).closest("dialog") !== dialog) return;
    const items = Array.from(dialog.querySelectorAll<HTMLElement>(POPUP_FOCUSABLE)).filter((el) => el.tabIndex >= 0 && !el.hasAttribute("disabled") && el.getClientRects().length > 0);
    const to = popupTabWrap(items.indexOf(document.activeElement as HTMLElement), items.length, event.shiftKey);
    if (to !== null) {
      event.preventDefault();
      items[to].focus();
    }
  };
  const label = modal ? popupBackLabel(backLabel) : backLabel;
  const header = (
    <header className="sheet-header">
      <button type="button" className={label === POPUP_CLOSE && modal ? "sheet-back popup-close" : "sheet-back"} onClick={onBack}>
        {label === POPUP_CLOSE && modal ? (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        ) : (
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        )}
        {label}
      </button>
      <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>
        {title}
      </h2>
      {extra}
    </header>
  );
  if (!popup)
    return (
      <section id={id} className="sheet" aria-labelledby={`${id}-title`} hidden={!open} onKeyDown={onKeyDown}>
        {header}
        {children}
      </section>
    );
  return (
    <dialog
      ref={dialogRef}
      id={id}
      className="sheet popup-sheet"
      aria-labelledby={`${id}-title`}
      hidden={!open}
      onKeyDown={onKeyDown}
      // Escape is the key handler's (it leaves a nested dialog's and the place search's alone); the sheet closes by
      // the app's state, never by the browser alone.
      onCancel={(event) => event.preventDefault()}
      onClick={(event) => {
        // A press on the dimmed map around the popup closes it, as a press on Close does.
        if (!modal || event.target !== event.currentTarget) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientY < box.top || event.clientY > box.bottom || event.clientX < box.left || event.clientX > box.right) onBack();
      }}
    >
      {/* First, so the hidden line sits at the popup's top and never lengthens what scrolls. */}
      <p className="visually-hidden" role="status" aria-live="polite">
        {said.text}
        {said.count % 2 === 1 ? " " : ""}
      </p>
      {header}
      {children}
    </dialog>
  );
}
