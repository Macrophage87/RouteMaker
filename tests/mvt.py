"""A small Mapbox Vector Tile (v2) decoder, for the stress tile tests and proofs.

Only what the stress tiles use: layers, features, tags and line geometry,
decoded into tile coordinates. No dependency, because none of the project's
pinned packages reads MVT and the suite installs nothing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _fields(data: bytes):
    """(field number, wire type, value) for each field of one message."""
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if wire == 0:
            value, pos = _varint(data, pos)
        elif wire == 1:
            value, pos = data[pos : pos + 8], pos + 8
        elif wire == 2:
            size, pos = _varint(data, pos)
            value, pos = data[pos : pos + size], pos + size
        elif wire == 5:
            value, pos = data[pos : pos + 4], pos + 4
        else:
            raise ValueError(f"wire type {wire}")
        yield number, wire, value


def _packed(data: bytes) -> list[int]:
    out, pos = [], 0
    while pos < len(data):
        value, pos = _varint(data, pos)
        out.append(value)
    return out


def _zigzag(n: int) -> int:
    return (n >> 1) ^ -(n & 1)


def _value(data: bytes):
    for number, _wire, raw in _fields(data):
        if number == 1:
            return raw.decode()
        if number == 2:
            return struct.unpack("<f", raw)[0]
        if number == 3:
            return struct.unpack("<d", raw)[0]
        if number in (4, 5):
            return raw
        if number == 6:
            return _zigzag(raw)
        if number == 7:
            return bool(raw)
    return None


def _lines(commands: list[int]) -> list[list[tuple[int, int]]]:
    """Line geometry: each MoveTo starts a line, LineTo extends it."""
    lines: list[list[tuple[int, int]]] = []
    x = y = pos = 0
    while pos < len(commands):
        command, count = commands[pos] & 7, commands[pos] >> 3
        pos += 1
        if command == 7:  # ClosePath: not used by lines
            continue
        for _ in range(count):
            x += _zigzag(commands[pos])
            y += _zigzag(commands[pos + 1])
            pos += 2
            if command == 1:
                lines.append([(x, y)])
            else:
                lines[-1].append((x, y))
    return lines


@dataclass
class Feature:
    type: int
    properties: dict
    lines: list[list[tuple[int, int]]]


@dataclass
class Layer:
    name: str
    extent: int
    features: list[Feature] = field(default_factory=list)


def decode(tile: bytes) -> dict[str, Layer]:
    layers = {}
    for number, _wire, raw in _fields(tile):
        if number != 3:
            continue
        name, extent, keys, values, features = "", 4096, [], [], []
        for n, _w, v in _fields(raw):
            if n == 1:
                name = v.decode()
            elif n == 2:
                features.append(v)
            elif n == 3:
                keys.append(v.decode())
            elif n == 4:
                values.append(_value(v))
            elif n == 5:
                extent = v
        layer = Layer(name, extent)
        for raw_feature in features:
            tags, geometry, kind = [], [], 0
            for n, _w, v in _fields(raw_feature):
                if n == 2:
                    tags = _packed(v)
                elif n == 3:
                    kind = v
                elif n == 4:
                    geometry = _packed(v)
            properties = {keys[tags[i]]: values[tags[i + 1]] for i in range(0, len(tags), 2)}
            layer.features.append(Feature(kind, properties, _lines(geometry)))
        layers[name] = layer
    return layers
