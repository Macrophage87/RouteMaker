import { test } from "node:test";
import assert from "node:assert/strict";
import { BATTERY_PLUGIN, batteryNoteDue, markBatteryNoteSeen, openBatterySettings, type Shown } from "./batteryNote.ts";
import type { CapacitorBridge } from "./nativeShell.ts";

function bridge(answer: unknown, plugins = [BATTERY_PLUGIN]) {
  const calls: string[] = [];
  const fake: CapacitorBridge = {
    isNativePlatform: () => true,
    isPluginAvailable: (name) => plugins.includes(name),
    nativePromise: async (plugin, method) => {
      calls.push(`${plugin}.${method}`);
      if (answer instanceof Error) throw answer;
      return answer;
    },
    nativeCallback: () => "",
  };
  return { fake, calls };
}

function memory(): Shown & { value: boolean } {
  const box = { value: false, get: () => box.value, set: () => void (box.value = true) };
  return box;
}

test("shown until dismissed, only for an optimised app on a maker known to stop rides", async () => {
  const shown = memory();
  assert.equal(await batteryNoteDue(bridge({ optimised: true, strictMaker: true }).fake, shown), true);
  assert.equal(shown.value, false, "not marked until the rider closes it: a line drawn unread comes back");
  assert.equal(await batteryNoteDue(bridge({ optimised: true, strictMaker: true }).fake, shown), true);
  markBatteryNoteSeen(shown);
  assert.equal(await batteryNoteDue(bridge({ optimised: true, strictMaker: true }).fake, shown), false, "once closed, never again");
  for (const answer of [{ optimised: false, strictMaker: true }, { optimised: true, strictMaker: false }, null, new Error("no")]) {
    const fresh = memory();
    assert.equal(await batteryNoteDue(bridge(answer).fake, fresh), false, JSON.stringify(answer));
    assert.equal(fresh.value, false, "not marked when not shown");
  }
});

test("a browser, or an app built before the plugin, shows nothing and asks nothing", async () => {
  assert.equal(await batteryNoteDue(null, memory()), false);
  const old = bridge({ optimised: true, strictMaker: true }, []);
  assert.equal(await batteryNoteDue(old.fake, memory()), false);
  assert.deepEqual(old.calls, []);
});

test("the button opens the app's settings page", async () => {
  const { fake, calls } = bridge(undefined);
  assert.equal(await openBatterySettings(fake), true);
  assert.deepEqual(calls, [`${BATTERY_PLUGIN}.openSettings`]);
  assert.equal(await openBatterySettings(null), false);
});
