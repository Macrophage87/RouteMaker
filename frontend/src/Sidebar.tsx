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
import { useId, useState, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { BAR_ITEMS, BAR_NAME, FEWER_TIPS, MORE_TIPS, barCurrent, sheetEscape, type BarItem, type PanelView } from "./lib/sidebar.ts";
import type { QuickFigure } from "./lib/quickFigures.ts";

// The parts a test renders are written with createElement in lib/sidebarParts.ts (node's test runner
// reads .ts, not .tsx); App.tsx takes them from here with the rest.
export { HighContrastShortcut, Fold, JunctionLegend, PlannerZoomNotice, RideSettings } from "./lib/sidebarParts.ts";

/** Help that is not needed every time, behind a toggle (the mockup's "More tips"). */
export function MoreTips({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <div className="more-tips">
      <button type="button" className="link tips-toggle" aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)}>
        {open ? FEWER_TIPS : MORE_TIPS}
      </button>
      <div id={id} className="tips-body" hidden={!open}>
        {children}
      </div>
    </div>
  );
}

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

const ICONS: Record<BarItem["id"], ReactNode> = {
  layers: <path d="M12 3 3 8l9 5 9-5-9-5zM3 13l9 5 9-5" />,
  legend: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v4M12 16h.01" />
    </>
  ),
  gpx: <path d="M12 4v11M7 10l5 5 5-5M5 20h14" />,
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
    </>
  ),
};

/** The bottom bar: real buttons, each with an icon (hidden from screen readers) and its words. */
export function BottomBar({
  view,
  legend,
  onOpen,
  buttonRef,
}: {
  view: PanelView;
  /** Whether the layers sheet was opened by Legend, so that button is the current one. */
  legend: boolean;
  onOpen: (item: BarItem) => void;
  buttonRef: (id: BarItem["id"], button: HTMLButtonElement | null) => void;
}) {
  return (
    <nav aria-label={BAR_NAME} className="bottom-bar">
      {BAR_ITEMS.map((item) => {
        const current = barCurrent(item, view, legend);
        return (
          <button
            key={item.id}
            type="button"
            ref={(button) => buttonRef(item.id, button)}
            className="bar-button"
            aria-current={current ? "true" : undefined}
            aria-describedby={`bar-${item.id}-hint`}
            onClick={() => onOpen(item)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              {ICONS[item.id]}
            </svg>
            <span>{item.label}</span>
            <span id={`bar-${item.id}-hint`} className="visually-hidden">
              {item.description}
            </span>
          </button>
        );
      })}
    </nav>
  );
}

/**
 * One of the bottom bar's sheets: a header with a Back button and a heading,
 * over its content. It stays in the page when hidden, so what it holds (the
 * opened GPX file, the switches) keeps its state.
 */
export function SheetFrame({
  id,
  title,
  open,
  onBack,
  headingRef,
  children,
}: {
  id: string;
  title: string;
  open: boolean;
  onBack: () => void;
  headingRef: Ref<HTMLHeadingElement>;
  children: ReactNode;
}) {
  // Escape inside a nested dialog or the place search's list is theirs, not the sheet's (lib/sidebar.ts).
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    sheetEscape({ key: event.key, defaultPrevented: event.defaultPrevented, target: event.target as HTMLElement, preventDefault: () => event.preventDefault() }, onBack);
  };
  return (
    <section id={id} className="sheet" aria-labelledby={`${id}-title`} hidden={!open} onKeyDown={onKeyDown}>
      <header className="sheet-header">
        <button type="button" className="sheet-back" aria-label="Back to the planner" onClick={onBack}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
        </button>
        <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>
          {title}
        </h2>
      </header>
      {children}
    </section>
  );
}
