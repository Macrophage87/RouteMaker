# Front-end tests

`npm test` runs every `src/**/*.test.{ts,tsx,mjs}` with Node's own test runner. Plain `.ts` runs through Node's
type stripping; a `.test.tsx` can import and render the interface's components, through the hooks in
`src/testSupport/register.mjs` (Vite's own JSX transform) and happy-dom's DOM.

## Test what the rider sees

Render the component and check what it shows and does:

```tsx
import { click, render } from "./testSupport/render.ts";

const screen = await render(<RideTypePicker preset="default" dials={startDials("default")} onChoose={onChoose} />);
await click(screen.button(/Change$/));
assert.ok(screen.dialog("Choose a ride type"));
```

`screen.get(role, name)`, `screen.all(role, name)`, `screen.button(name)`, `screen.dialog(name)` and `screen.text()`
look at the page as a screen reader would (aria-hidden text is left out of names); `click`, `type` and `press`
act as a rider would. Each test's screens are unmounted after it. `src/RideTypePicker.test.tsx` is the example.

`import.meta.env` (Vite's build values) reads as a test build's (`DEV`, `MODE: "test"`) in `.tsx` files only; a
plain `.ts` module still runs under Node's own type stripping, where it is undefined, so read it with `?.` there.

## No new tests that read source as text

A test that reads `App.tsx`, `RideMode.tsx`, `styles.css` or another source file with `readFileSync` (or
`appSource.mjs`) and matches it with regular expressions passes while the screen is broken and fails when
working code is only reformatted. `src/sourceTextTests.test.ts` fails on any new test file that does this.
The files that still do are listed in `src/testSupport/sourceTextTests.txt`, which only shrinks:

- Converting: when work touches a component, move its source-text checks into a rendered test, and take
  the file off the list once it reads no source.
- What a DOM in Node cannot show (layout, colours, the CSS grid) stays in the browser suite
  (`scripts/a11y/check.mjs`), not a regular expression over `styles.css`, for new checks.
