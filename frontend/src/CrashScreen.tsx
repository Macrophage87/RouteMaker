import { Component, useEffect, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { crashReport, loggedErrors } from "./lib/crashReport.ts";
import { copyText, selectionCopy } from "./lib/sidebar.ts";

/**
 * In place of the whole page when an error stops it (Stephen 2026-10-25: "The website is just going completely black
 * at random intervals"; then "can you have the reload screen offer a way to dump the error log"): what happened, a
 * Reload (the plan is in the link, so it comes back), and the error report to copy into a bug report
 * (lib/crashReport.ts). Without this, React takes the whole page down and leaves the bare background.
 */
export class CrashBoundary extends Component<{ children: ReactNode }, { error: unknown; componentStack: string | null; at: number } | { error: null }> {
  state: { error: unknown; componentStack: string | null; at: number } | { error: null } = { error: null };

  static getDerivedStateFromError(error: unknown) {
    return { error: error ?? new Error("Unknown error"), componentStack: null, at: Date.now() };
  }

  componentDidCatch(_error: unknown, info: ErrorInfo) {
    this.setState((state) => (state.error === null ? state : { ...state, componentStack: info.componentStack ?? null }));
  }

  render() {
    if (this.state.error === null) return this.props.children;
    const { error, componentStack, at } = this.state;
    const report = crashReport({
      error,
      componentStack,
      at,
      hash: window.location.hash,
      path: window.location.pathname,
      userAgent: navigator.userAgent,
      logged: loggedErrors(),
    });
    return <CrashScreen report={report} />;
  }
}

/** The screen itself: Reload first, then Copy error report, the report itself behind Show. */
export function CrashScreen({ report }: { report: string }) {
  const heading = useRef<HTMLHeadingElement>(null);
  const [said, setSaid] = useState("");
  const details = useRef<HTMLDetailsElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  useEffect(() => heading.current?.focus(), []);
  const copy = async () => {
    const done = await copyText(report, navigator.clipboard, selectionCopy);
    setSaid(done ? "Error report copied. Paste it into your bug report." : "Could not copy. Copy it from the report below.");
    if (!done && details.current) {
      // The report is opened and selected, so the rider can copy it by hand.
      details.current.open = true;
      box.current?.focus();
      box.current?.select();
    }
  };
  return (
    <main className="crash-screen">
      <h1 ref={heading} tabIndex={-1}>
        Something went wrong
      </h1>
      <p>RouteMaker hit an error. Reload to carry on: your route comes back with the page.</p>
      <div className="crash-actions">
        <button type="button" onClick={() => window.location.reload()}>
          Reload
        </button>
        <button type="button" className="secondary" onClick={() => void copy()}>
          Copy error report
        </button>
      </div>
      <p className="crash-said" role="status">
        {said}
      </p>
      <details className="crash-details" ref={details}>
        <summary>Show the report</summary>
        <textarea ref={box} readOnly value={report} aria-label="Error report" rows={12} />
      </details>
    </main>
  );
}
