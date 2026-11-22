// Sharing a route's link where there is no share sheet (Stephen 2026-11-22: "It's not intuitive to copy a link when no
// share sheet", and "After saving, you should also be able to copy/share a link"), as the rider sees it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { ShareControls } from "./app/RoutePanel.tsx";
import { SaveRoute } from "./SaveRoute.tsx";
import { SHARE_KEEP_DEFAULT } from "./lib/sharedRoutes.ts";

const LINK = "https://routemakerdc.com/#q=abc";

function controls(over: Partial<Parameters<typeof ShareControls>[0]> = {}) {
  return (
    <ShareControls
      save={null}
      ready
      shareRoute={() => {}}
      shareKeep={SHARE_KEEP_DEFAULT}
      onShareKeep={null}
      shareSaid={{ text: "", count: 0 }}
      shareBox=""
      linkNote=""
      {...over}
    />
  );
}

test("Save & load offers Share route and Share ride even where the browser has no share sheet", async () => {
  const pressed: boolean[] = [];
  const screen = await render(controls({ shareRoute: (ride) => pressed.push(ride) }));
  await click(screen.button("Share route"));
  await click(screen.button("Share ride"));
  assert.deepEqual(pressed, [false, true]);
});

test("a link copied in the sheet's place is said, with no box", async () => {
  const screen = await render(controls({ shareSaid: { text: "Link copied.", count: 1 } }));
  assert.match(screen.text(), /Link copied\./);
  assert.equal(screen.all("textbox").length, 0);
});

test("a link neither shared nor copied is shown in a box to select and copy", async () => {
  const screen = await render(controls({ shareSaid: { text: "Could not copy the link. Select it below and copy it.", count: 1 }, shareBox: LINK }));
  assert.match(screen.text(), /Select it below and copy it\./);
  const box = screen.get("textbox", "Link") as HTMLInputElement;
  assert.equal(box.value, LINK);
  assert.equal(box.readOnly, true);
});

async function saved(onShare: () => Promise<{ said: string; box: string }>) {
  const screen = await render(<SaveRoute label="Save route" defaultName={() => "Home to Work"} onSave={async () => "Saved as Home to Work."} onShare={onShare} />);
  assert.equal(screen.all("button", "Share route").length, 0, "no Share before a save");
  await click(screen.button("Save route"));
  await click(screen.button("Save"));
  for (let i = 0; i < 20 && !screen.text().includes("Saved as"); i++) await new Promise((r) => setTimeout(r, 5));
  return screen;
}

test("after saving, Share route is on the saved line, and a copy is said there", async () => {
  let asked = 0;
  const screen = await saved(async () => {
    asked++;
    return { said: "Link copied.", box: "" };
  });
  assert.match(screen.text(), /Saved as Home to Work\./);
  await click(screen.button("Share route"));
  await new Promise((r) => setTimeout(r, 5));
  assert.equal(asked, 1);
  assert.match(screen.text(), /Link copied\./);
  assert.equal(screen.all("textbox", "Link").length, 0);
});

test("after saving, a link that could not be shared or copied shows in a box", async () => {
  const screen = await saved(async () => ({ said: "Could not copy the link. Select it below and copy it.", box: LINK }));
  await click(screen.button("Share route"));
  await new Promise((r) => setTimeout(r, 5));
  assert.equal((screen.get("textbox", "Link") as HTMLInputElement).value, LINK);
});

test("the sheet opening keeps the saved line as it was", async () => {
  const screen = await saved(async () => ({ said: "", box: "" }));
  await click(screen.button("Share route"));
  await new Promise((r) => setTimeout(r, 5));
  assert.match(screen.text(), /Saved as Home to Work\./);
});

test("a save that failed offers no Share on its line", async () => {
  const screen = await render(
    <SaveRoute label="Save route" defaultName={() => "Home to Work"} onSave={async () => "Could not save."} savedOk={() => false} onShare={async () => ({ said: "", box: "" })} />,
  );
  await click(screen.button("Save route"));
  await click(screen.button("Save"));
  for (let i = 0; i < 20 && !screen.text().includes("Could not save"); i++) await new Promise((r) => setTimeout(r, 5));
  assert.equal(screen.all("button", "Share route").length, 0);
});
