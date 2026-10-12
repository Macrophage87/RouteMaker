// The planner's source as one text, for the tests that read App.tsx's wiring (UI-CLEANUP step 4).
//
// App.tsx was split into app/Planner.tsx, app/RoutePanel.tsx and app/Sheets.tsx with no change in
// behaviour: App keeps the state and the effects and renders <PointsSection {...{ ... }} /> and the
// rest, each passing App's own names through. Those tests check what App renders and in what order, so
// this puts each component's JSX back where App renders it, then adds the rest of each module (its
// imports, a component's own constants, RouteSummary, the hooks). A test then reads the planner as it
// read the single file.
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

/** The JSX `name` returns: what is between its `return (` and the `  );\n}` that closes it. */
function returned(source, name) {
  const start = source.indexOf(`export function ${name}(`);
  if (start < 0) throw new Error(`appSource: no component ${name}`);
  const open = source.indexOf("  return (\n", start);
  const close = source.indexOf("\n  );\n}\n", open);
  if (open < 0 || close < 0) throw new Error(`appSource: no return in ${name}`);
  const pre = source.slice(source.indexOf("\n", source.indexOf(" = props;", start)) + 1, open);
  return { jsx: source.slice(open + "  return (\n".length, close), pre, start, end: close + "\n  );\n}\n".length };
}

let cached = null;

/** App.tsx with the planner, route panel and sheet components' JSX in place, then the rest of those modules. */
export function appSource() {
  if (cached !== null) return cached;
  let app = read("../App.tsx");
  const modules = ["../app/Planner.tsx", "../app/RoutePanel.tsx", "../app/Sheets.tsx", "../app/Go.tsx"].map(read);
  const rest = [...modules];
  for (const [index, source] of modules.entries()) {
    for (const match of source.matchAll(/^export function (\w+)\(props: \w+Props\)/gm)) {
      const name = match[1];
      const call = new RegExp(`<${name}( key="\\w+")?\\n\\s*\\{\\.\\.\\.\\{[\\s\\S]*?\\}\\}\\n\\s*/>`);
      if (!call.test(app)) throw new Error(`appSource: App.tsx does not render ${name}`);
      const { jsx, pre } = returned(source, name);
      app = app.replace(call, () => jsx.trim());
      const { start, end } = returned(rest[index], name);
      rest[index] = rest[index].slice(0, start) + pre + rest[index].slice(end);
    }
  }
  // The props interfaces only repeat App's names and types for the pass-through; with the JSX back in
  // place they would read as uses of App's state that the original file did not have.
  const withoutProps = rest.map((source) => source.replace(/^export interface \w+Props \{\n[\s\S]*?^\}\n/gm, ""));
  cached = [app, ...withoutProps, read("../app/hooks.ts")].join("\n");
  return cached;
}
