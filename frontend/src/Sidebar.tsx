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
import { Fragment, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { BACK_LABEL, BAR_ITEMS, BAR_NAME, barCurrent, sheetEscape, type BarItem, type PanelView } from "./lib/sidebar.ts";
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
 */
export function SheetFrame({
  id,
  title,
  open,
  onBack,
  headingRef,
  backLabel = BACK_LABEL,
  extra,
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
  children: ReactNode;
}) {
  // Escape inside a nested dialog or the place search's list is theirs, not the sheet's (lib/sidebar.ts).
  const onKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    sheetEscape({ key: event.key, defaultPrevented: event.defaultPrevented, target: event.target as HTMLElement, preventDefault: () => event.preventDefault() }, onBack);
  };
  return (
    <section id={id} className="sheet" aria-labelledby={`${id}-title`} hidden={!open} onKeyDown={onKeyDown}>
      <header className="sheet-header">
        <button type="button" className="sheet-back" onClick={onBack}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          {backLabel}
        </button>
        <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>
          {title}
        </h2>
        {extra}
      </header>
      {children}
    </section>
  );
}
