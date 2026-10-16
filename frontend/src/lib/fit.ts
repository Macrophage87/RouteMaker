/**
 * A FIT course file, written here to the FIT protocol (Garmin's published FIT Protocol and Global Profile, read
 * 2026-10-16), with no library. PLAN.md, Formats, rejects Garmin's own SDK on licence grounds; the course this
 * writes needs only the protocol's plain records, a few hundred lines with the CRC, so no third-party encoder is
 * shipped either (docs/DEVELOPMENT.md, "Course export").
 *
 * The message set Garmin requires for a course to load (PLAN.md: "a `file_id` of type course, a `course`
 * message, a `lap` message carrying totals, the records, the course points, and start and stop events"), in this
 * order: file_id, course, lap, event (timer start), record..., event (timer stop), course_point....
 *
 * Clean (PLAN.md, Clean exports): file_id has no serial number and the manufacturer is "development" (255), so no
 * device or account is named, and its number is a hash of the file's own bytes (fileNumber); there is no file_creator, user profile or device_info message. Every timestamp is
 * the course's fixed base plus the route's own pace (course.ts), so the same route gives the same bytes. FIT has
 * no free-text notice field: the OpenStreetMap credit goes in the course name where it fits (course.ts
 * courseName), and otherwise on the GPX section beside the download (PLAN.md's recorded FIT carve-out).
 */
import type { Course, CourseCueType } from "./course.ts";

/** FIT's epoch, 1989-12-31T00:00:00Z, in seconds since 1970. */
export const FIT_EPOCH_UNIX_S = 631_065_600;
/** Protocol 1.0 (every type here is a 1.0 type) and Global Profile 21.00. */
export const FIT_PROTOCOL_VERSION = 0x10;
export const FIT_PROFILE_VERSION = 2100;

/** Global message numbers (Global Profile, mesg_num). */
export const MESG = { fileId: 0, lap: 19, record: 20, event: 21, course: 31, coursePoint: 32 } as const;

/** Global Profile enums used here. */
export const FILE_COURSE = 6;
export const MANUFACTURER_DEVELOPMENT = 255;
export const SPORT_CYCLING = 2;
export const EVENT_TIMER = 0;
export const EVENT_LAP = 9;
export const EVENT_TYPE_START = 0;
export const EVENT_TYPE_STOP = 1;
export const EVENT_TYPE_STOP_ALL = 4;

/**
 * course_point type for each cue (Global Profile, course_point): the published mapping. FIT has slight, sharp,
 * fork and u-turn types too; the turn model produces none of them yet, so none is written. Danger is only the
 * warnings never dropped (Avoid, work zones); a flagged crossing, which can be dropped, is a note.
 */
export const FIT_CUE_TYPES: Record<CourseCueType, number> = {
  start: 0, // generic
  finish: 0, // generic
  stop: 0, // generic
  walk: 0, // generic
  note: 0, // generic
  danger: 5,
  left: 6,
  right: 7,
};

type BaseType = "enum" | "uint8" | "uint16" | "sint32" | "uint32" | "string";

/** Base type number, size and invalid value (FIT Protocol, base types). */
const BASE: Record<BaseType, { id: number; size: number; invalid: number }> = {
  enum: { id: 0x00, size: 1, invalid: 0xff },
  uint8: { id: 0x02, size: 1, invalid: 0xff },
  uint16: { id: 0x84, size: 2, invalid: 0xffff },
  sint32: { id: 0x85, size: 4, invalid: 0x7fffffff },
  uint32: { id: 0x86, size: 4, invalid: 0xffffffff },
  string: { id: 0x07, size: 1, invalid: 0 },
};

interface FieldDef {
  num: number;
  type: BaseType;
  /** Bytes, for a string (null-padded). */
  size?: number;
}

type Value = number | string | null;

const CRC_TABLE = [0x0000, 0xcc01, 0xd801, 0x1400, 0xf001, 0x3c00, 0x2800, 0xe401, 0xa001, 0x6c00, 0x7800, 0xb401, 0x5000, 0x9c01, 0x8801, 0x4400];

/** FIT's CRC-16 (FIT Protocol, "CRC"). */
export function fitCrc(bytes: Uint8Array, from = 0, to = bytes.length): number {
  let crc = 0;
  for (let i = from; i < to; i += 1) {
    const byte = bytes[i];
    let tmp = CRC_TABLE[crc & 0xf];
    crc = (crc >> 4) & 0x0fff;
    crc = crc ^ tmp ^ CRC_TABLE[byte & 0xf];
    tmp = CRC_TABLE[crc & 0xf];
    crc = (crc >> 4) & 0x0fff;
    crc = crc ^ tmp ^ CRC_TABLE[(byte >> 4) & 0xf];
  }
  return crc;
}

/** Degrees as FIT's semicircles (2^31 to 180 degrees). */
export function semicircles(degrees: number): number {
  return Math.round((degrees * 2 ** 31) / 180);
}

const encoder = new TextEncoder();

/** UTF-8 bytes of `text`, cut on a character boundary to leave room for the terminating null in `size`. */
function stringBytes(text: string, size: number): Uint8Array {
  const out = new Uint8Array(size);
  let used = 0;
  for (const ch of text) {
    const b = encoder.encode(ch);
    if (used + b.length > size - 1) break;
    out.set(b, used);
    used += b.length;
  }
  return out;
}

class FitWriter {
  private chunks: number[] = [];
  private defs = new Map<number, FieldDef[]>();

  define(local: number, global: number, fields: FieldDef[]): void {
    this.defs.set(local, fields);
    // Record header: definition (bit 6), local message type; reserved, little-endian architecture.
    this.chunks.push(0x40 | local, 0, 0, global & 0xff, global >> 8, fields.length);
    for (const f of fields) this.chunks.push(f.num, f.size ?? BASE[f.type].size, BASE[f.type].id);
  }

  /** Bytes written so far, after the header. */
  get length(): number {
    return this.chunks.length;
  }

  /** FNV-1a (32-bit) of the bytes written from `from` on. */
  hashFrom(from: number): number {
    let h = 0x811c9dc5;
    for (let i = from; i < this.chunks.length; i += 1) h = Math.imul(h ^ this.chunks[i], 0x01000193) >>> 0;
    return h;
  }

  /** Overwrites a little-endian uint16 already written at `at`. */
  patchUint16(at: number, value: number): void {
    this.chunks[at] = value & 0xff;
    this.chunks[at + 1] = (value >> 8) & 0xff;
  }

  write(local: number, values: Value[]): void {
    const fields = this.defs.get(local);
    if (!fields || fields.length !== values.length) throw new Error(`FIT: no definition for local message ${local}`);
    this.chunks.push(local);
    fields.forEach((f, i) => {
      const v = values[i];
      if (f.type === "string") {
        this.chunks.push(...stringBytes(typeof v === "string" ? v : "", f.size ?? 1));
        return;
      }
      const base = BASE[f.type];
      const n = typeof v === "number" && Number.isFinite(v) ? Math.round(v) : base.invalid;
      for (let b = 0; b < base.size; b += 1) this.chunks.push((n >>> (8 * b)) & 0xff);
    });
  }

  /** The whole file: the 14-byte header with its CRC, the records, and the file's CRC. */
  bytes(): Uint8Array<ArrayBuffer> {
    const data = this.chunks;
    const out = new Uint8Array(14 + data.length + 2);
    out[0] = 14;
    out[1] = FIT_PROTOCOL_VERSION;
    out[2] = FIT_PROFILE_VERSION & 0xff;
    out[3] = FIT_PROFILE_VERSION >> 8;
    new DataView(out.buffer).setUint32(4, data.length, true);
    out.set([0x2e, 0x46, 0x49, 0x54], 8); // ".FIT"
    const headerCrc = fitCrc(out, 0, 12);
    out[12] = headerCrc & 0xff;
    out[13] = headerCrc >> 8;
    out.set(data, 14);
    const crc = fitCrc(out, 0, 14 + data.length);
    out[14 + data.length] = crc & 0xff;
    out[15 + data.length] = crc >> 8;
    return out;
  }
}

/** A string field's size in bytes: room for the longest of `texts` and its null. */
function sizeFor(texts: readonly string[]): number {
  return Math.max(1, ...texts.map((t) => encoder.encode(t).length)) + 1;
}

/** Altitude as FIT writes it, (m + 500) * 5, held to uint16 below its invalid value (-500 m to 12,606.8 m). */
export function fitAltitude(metres: number): number {
  return Math.min(Math.max(Math.round((metres + 500) * 5), 0), BASE.uint16.invalid - 1);
}

/**
 * file_id's number: the file's own bytes after file_id hashed (FNV-1a) and folded to 16 bits, so two courses do
 * not share a file_id (a unit can take a second as the first) while the same course gives the same bytes. Never
 * the invalid value.
 */
export function fileNumber(hash: number): number {
  const n = ((hash >>> 16) ^ hash) & 0xffff;
  return n === BASE.uint16.invalid ? n - 1 : n;
}

/** The FIT course file for a compiled course (course.ts compileCourse with format "fit"). */
export function writeFit(course: Course): Uint8Array<ArrayBuffer> {
  const w = new FitWriter();
  const t0 = course.baseUnixS - FIT_EPOCH_UNIX_S;
  const at = (s: number) => t0 + Math.round(s);
  const first = course.records[0];
  const last = course.records[course.records.length - 1];
  const end = at(course.totalS);

  w.define(0, MESG.fileId, [
    { num: 0, type: "enum" }, // type
    { num: 1, type: "uint16" }, // manufacturer
    { num: 2, type: "uint16" }, // product
    { num: 4, type: "uint32" }, // time_created
    { num: 5, type: "uint16" }, // number: set below from the file's own bytes
  ]);
  w.write(0, [FILE_COURSE, MANUFACTURER_DEVELOPMENT, 0, t0, 0]);
  const numberAt = w.length - 2;
  const afterFileId = w.length;

  w.define(1, MESG.course, [
    { num: 5, type: "string", size: sizeFor([course.name]) }, // name
    { num: 4, type: "enum" }, // sport
  ]);
  w.write(1, [course.name, SPORT_CYCLING]);

  w.define(2, MESG.lap, [
    { num: 253, type: "uint32" }, // timestamp
    { num: 0, type: "enum" }, // event
    { num: 1, type: "enum" }, // event_type
    { num: 2, type: "uint32" }, // start_time
    { num: 3, type: "sint32" }, // start_position_lat
    { num: 4, type: "sint32" }, // start_position_long
    { num: 5, type: "sint32" }, // end_position_lat
    { num: 6, type: "sint32" }, // end_position_long
    { num: 7, type: "uint32" }, // total_elapsed_time, ms
    { num: 8, type: "uint32" }, // total_timer_time, ms
    { num: 9, type: "uint32" }, // total_distance, cm
    { num: 21, type: "uint16" }, // total_ascent, m
    { num: 22, type: "uint16" }, // total_descent, m
  ]);
  w.write(2, [
    end,
    EVENT_LAP,
    EVENT_TYPE_STOP,
    t0,
    first ? semicircles(first.lat) : null,
    first ? semicircles(first.lon) : null,
    last ? semicircles(last.lat) : null,
    last ? semicircles(last.lon) : null,
    course.totalS * 1000,
    course.totalS * 1000,
    course.totalM * 100,
    course.climbM,
    course.descentM,
  ]);

  w.define(3, MESG.event, [
    { num: 253, type: "uint32" }, // timestamp
    { num: 0, type: "enum" }, // event
    { num: 1, type: "enum" }, // event_type
    { num: 4, type: "uint8" }, // event_group
  ]);
  w.write(3, [t0, EVENT_TIMER, EVENT_TYPE_START, 0]);

  w.define(4, MESG.record, [
    { num: 253, type: "uint32" }, // timestamp
    { num: 0, type: "sint32" }, // position_lat
    { num: 1, type: "sint32" }, // position_long
    { num: 2, type: "uint16" }, // altitude, (m + 500) * 5
    { num: 5, type: "uint32" }, // distance, cm
  ]);
  for (const r of course.records) {
    w.write(4, [at(r.timeS), semicircles(r.lat), semicircles(r.lon), r.ele === null ? null : fitAltitude(r.ele), r.distM * 100]);
  }

  w.write(3, [end, EVENT_TIMER, EVENT_TYPE_STOP_ALL, 0]);

  if (course.cues.length && course.records.length) {
    w.define(5, MESG.coursePoint, [
      { num: 254, type: "uint16" }, // message_index
      { num: 1, type: "uint32" }, // timestamp
      { num: 2, type: "sint32" }, // position_lat
      { num: 3, type: "sint32" }, // position_long
      { num: 4, type: "uint32" }, // distance, cm
      { num: 5, type: "enum" }, // type
      { num: 6, type: "string", size: sizeFor(course.cues.map((c) => c.name)) }, // name
    ]);
    course.cues.forEach((c, i) => {
      const r = course.records[c.vertex];
      w.write(5, [i, at(r.timeS), semicircles(r.lat), semicircles(r.lon), r.distM * 100, FIT_CUE_TYPES[c.type], c.name]);
    });
  }
  w.patchUint16(numberAt, fileNumber(w.hashFrom(afterFileId)));
  return w.bytes();
}
