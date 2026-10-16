// FIT course files (lib/fit.ts), checked by decoding them back: a reader written here from the FIT protocol,
// driven by each file's own definition messages and CRCs rather than by the writer's tables, so the round trip
// tests the bytes and not just the writer agreeing with itself.
import { test } from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_PROFILE, deviceProfile, type DeviceProfile } from "./deviceProfiles.ts";
import { compileCourse, COURSE_BASE_UNIX_S } from "./course.ts";
import { FIT_EPOCH_UNIX_S, fitCrc, semicircles, writeFit } from "./fit.ts";
import { sampleRoute } from "./courseRoute.test.fixture.ts";

interface Message {
  global: number;
  fields: Map<number, number | string>;
}

/** Every data message of a FIT file, fields by number; throws on a bad header, size or CRC. */
function readFit(bytes: Uint8Array): { protocol: number; profile: number; messages: Message[] } {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerSize = bytes[0];
  assert.equal(headerSize, 14);
  assert.equal(String.fromCharCode(...bytes.slice(8, 12)), ".FIT");
  assert.equal(view.getUint16(12, true), fitCrc(bytes, 0, 12), "header CRC");
  const dataSize = view.getUint32(4, true);
  assert.equal(bytes.length, headerSize + dataSize + 2, "data size");
  assert.equal(view.getUint16(headerSize + dataSize, true), fitCrc(bytes, 0, headerSize + dataSize), "file CRC");
  assert.equal(fitCrc(bytes), 0, "a FIT file's CRC over itself is 0");
  const defs = new Map<number, { global: number; little: boolean; fields: { num: number; size: number; base: number }[] }>();
  const messages: Message[] = [];
  let i = headerSize;
  const end = headerSize + dataSize;
  while (i < end) {
    const header = bytes[i++];
    assert.equal(header & 0x80, 0, "normal headers only");
    const local = header & 0x0f;
    if (header & 0x40) {
      assert.equal(header & 0x20, 0, "no developer fields");
      const little = bytes[i + 1] === 0;
      const global = little ? view.getUint16(i + 2, true) : view.getUint16(i + 2, false);
      const n = bytes[i + 4];
      const fields = [];
      for (let f = 0; f < n; f += 1) fields.push({ num: bytes[i + 5 + 3 * f], size: bytes[i + 6 + 3 * f], base: bytes[i + 7 + 3 * f] });
      defs.set(local, { global, little, fields });
      i += 5 + 3 * n;
      continue;
    }
    const def = defs.get(local);
    assert.ok(def, `data before its definition (local ${local})`);
    const values = new Map<number, number | string>();
    for (const f of def.fields) {
      const kind = f.base & 0x1f;
      let v: number | string;
      if (kind === 0x07) {
        const raw = bytes.slice(i, i + f.size);
        const z = raw.indexOf(0);
        v = new TextDecoder().decode(z < 0 ? raw : raw.slice(0, z));
      } else if (f.size === 1) v = kind === 0x01 ? view.getInt8(i) : bytes[i];
      else if (f.size === 2) v = kind === 0x03 ? view.getInt16(i, def.little) : view.getUint16(i, def.little);
      else if (f.size === 4) v = kind === 0x05 ? view.getInt32(i, def.little) : view.getUint32(i, def.little);
      else throw new Error(`size ${f.size}`);
      values.set(f.num, v);
      i += f.size;
    }
    messages.push({ global: def.global, fields: values });
  }
  assert.equal(i, end);
  return { protocol: bytes[1], profile: view.getUint16(2, true), messages };
}

const GENERIC = deviceProfile(DEFAULT_PROFILE);

test("a FIT course decodes back: header, CRCs and Garmin's course message set, in order", () => {
  const course = compileCourse(sampleRoute(), GENERIC, "fit");
  const { protocol, profile, messages } = readFit(writeFit(course));
  assert.equal(protocol, 0x10);
  assert.equal(profile, 2100);
  const order = messages.map((m) => m.global);
  // file_id, course, lap, event start, records, event stop, course points.
  assert.deepEqual(order.slice(0, 4), [0, 31, 19, 21]);
  assert.equal(order.filter((g) => g === 20).length, course.records.length);
  const stop = order.lastIndexOf(21);
  assert.ok(order.slice(4, stop).every((g) => g === 20));
  assert.ok(order.slice(stop + 1).every((g) => g === 32));
  const fileId = messages[0].fields;
  assert.equal(fileId.get(0), 6, "type course");
  assert.equal(fileId.get(1), 255, "manufacturer development: no device named");
  assert.ok(!fileId.has(3), "no serial number");
  assert.equal(fileId.get(4), COURSE_BASE_UNIX_S - FIT_EPOCH_UNIX_S, "time_created is the fixed base, not the clock");
  assert.equal(messages[1].fields.get(5), "Default 1.9 mi");
  assert.equal(messages[1].fields.get(4), 2, "sport cycling");
  const lap = messages[2].fields;
  assert.equal(lap.get(9), Math.round(course.totalM * 100), "total distance, cm");
  assert.equal(lap.get(7), 600_000, "total elapsed time, ms");
  assert.equal(lap.get(21), 12);
  assert.equal(lap.get(22), 8);
  assert.deepEqual([messages[3].fields.get(0), messages[3].fields.get(1)], [0, 0], "timer start");
  assert.deepEqual([messages[stop].fields.get(0), messages[stop].fields.get(1)], [0, 4], "timer stop all");
  // No messages beyond the course set (no file_creator, device_info or user profile).
  assert.deepEqual([...new Set(order)].sort((a, b) => a - b), [0, 19, 20, 21, 31, 32]);
});

test("records carry the line, elevation and distance; course points the cues, on their records", () => {
  const course = compileCourse(sampleRoute(), GENERIC, "fit");
  const { messages } = readFit(writeFit(course));
  const records = messages.filter((m) => m.global === 20);
  records.forEach((r, i) => {
    const want = course.records[i];
    assert.equal(r.fields.get(0), semicircles(want.lat));
    assert.equal(r.fields.get(1), semicircles(want.lon));
    assert.ok(Math.abs(((r.fields.get(2) as number) / 5 - 500) - (want.ele ?? NaN)) <= 0.1, "altitude, scale 5 offset 500");
    assert.equal(r.fields.get(5), Math.round(want.distM * 100));
  });
  const t = records.map((r) => r.fields.get(253) as number);
  assert.ok(t.every((v, i) => i === 0 || v >= t[i - 1]), "timestamps never go back");
  const points = messages.filter((m) => m.global === 32);
  assert.deepEqual(
    points.map((p) => [p.fields.get(5), p.fields.get(6)]),
    [
      [0, "Start"],
      [6, "17th St NW"],
      [5, "Florida Ave NW"],
      [5, "Dupont Cir"],
      [0, "Stop 1"],
      [7, "Right"],
      [0, "Busy road"],
      [0, "Finish"],
    ],
  );
  points.forEach((p, i) => {
    assert.equal(p.fields.get(254), i, "message_index");
    const r = records[course.cues[i].vertex].fields;
    assert.deepEqual([p.fields.get(2), p.fields.get(3), p.fields.get(4), p.fields.get(1)], [r.get(0), r.get(1), r.get(5), r.get(253)], "pinned to its record");
  });
});

test("a profile's trimming reaches the FIT file, and names fit its length", () => {
  const tight: DeviceProfile = { ...GENERIC, maxCues: 5, maxPoints: 20, cueNameChars: 8 };
  const { messages } = readFit(writeFit(compileCourse(sampleRoute(), tight, "fit")));
  assert.equal(messages.filter((m) => m.global === 32).length, 5);
  assert.ok(messages.filter((m) => m.global === 20).length <= 20);
  for (const p of messages.filter((m) => m.global === 32)) assert.ok(Array.from(p.fields.get(6) as string).length <= 8);
});

test("FIT carries the OSM credit in the course name where the profile has room (PLAN.md's carve-out)", () => {
  const wide = deviceProfile("wahoo");
  const name = readFit(writeFit(compileCourse(sampleRoute({ distance_m: 3000 }), { ...wide, courseNameChars: 40 }, "fit"))).messages[1].fields.get(5);
  assert.equal(name, "Default route, 1.9 mi (3.0 km) © OSM");
});

test("the same route gives the same FIT bytes, and a different one different bytes", () => {
  const a = writeFit(compileCourse(sampleRoute(), GENERIC, "fit"));
  const b = writeFit(compileCourse(sampleRoute(), GENERIC, "fit"));
  assert.deepEqual(a, b);
  assert.notDeepEqual(a, writeFit(compileCourse(sampleRoute({ duration_s: 700 }), GENERIC, "fit")));
});

test("the CRC is FIT's: the protocol's own check value", () => {
  // CRC-16/ARC, which FIT's nibble table computes: 0xBB3D for "123456789".
  assert.equal(fitCrc(new TextEncoder().encode("123456789")), 0xbb3d);
  assert.equal(semicircles(180), 2 ** 31);
  assert.equal(semicircles(-77.05), -919242306);
});
