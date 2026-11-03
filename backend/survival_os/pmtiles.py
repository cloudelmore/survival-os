"""Cut a region out of a remote PMTiles v3 archive, using HTTP range requests.

Daily world builds are about 140 GB and last only days, so a region is cut from the newest one. No
checksum can be published for a cut, so each tile's gzip CRC is checked as it arrives.

The output holds its tiles right after a fixed 16 KiB opening, and the directories go last. A part
file is therefore usable for resuming as it stands, and finishing needs no second copy of the tiles.
"""

import gzip
import json
import math
import struct
import zlib
from array import array
from bisect import bisect_left
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol

HEADER_BYTES = 127
ROOT_BYTES = 16384
LEAF_SIZE = 4096
GZIP = 2
UNKNOWN = 0
JPEG = 3
WEBP = 4
# Tiles this close together in the source are fetched in one request.
MERGE_GAP = 256 * 1024
MAX_REQUEST = 32 * 1024 * 1024


class Reader(Protocol):
    def read(self, offset: int, length: int) -> bytes: ...


@dataclass
class Header:
    root_offset: int
    root_length: int
    metadata_offset: int
    metadata_length: int
    leaf_offset: int
    leaf_length: int
    tile_offset: int
    tile_length: int
    addressed_tiles: int
    tile_entries: int
    tile_contents: int
    clustered: bool
    internal_compression: int
    tile_compression: int
    tile_type: int
    min_zoom: int
    max_zoom: int
    bounds: tuple[int, int, int, int]
    center_zoom: int
    center: tuple[int, int]


FORMAT = "<7sB11Q6B4iB2i"


def parse_header(data: bytes) -> Header:
    if len(data) < HEADER_BYTES or data[:7] != b"PMTiles" or data[7] != 3:
        raise ValueError("Not a PMTiles version 3 archive")
    values = struct.unpack(FORMAT, data[:HEADER_BYTES])
    return Header(*values[2:13], bool(values[13]), *values[14:19], tuple(values[19:23]),
                  values[23], tuple(values[24:26]))


def pack_header(header: Header) -> bytes:
    return struct.pack(
        FORMAT, b"PMTiles", 3, header.root_offset, header.root_length, header.metadata_offset,
        header.metadata_length, header.leaf_offset, header.leaf_length, header.tile_offset,
        header.tile_length, header.addressed_tiles, header.tile_entries, header.tile_contents,
        int(header.clustered), header.internal_compression, header.tile_compression,
        header.tile_type, header.min_zoom, header.max_zoom, *header.bounds, header.center_zoom,
        *header.center)


def tile_id(z: int, x: int, y: int) -> int:
    """Position on the Hilbert curve that orders every PMTiles archive."""
    acc = (4 ** z - 1) // 3
    a, b, d = x, y, 0
    s = 1 << (z - 1) if z else 0
    while s:
        rx = 1 if a & s else 0
        ry = 1 if b & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                a, b = s - 1 - (a & (s - 1)), s - 1 - (b & (s - 1))
            else:
                a, b = a & (s - 1), b & (s - 1)
            a, b = b, a
        else:
            a, b = a & (s - 1), b & (s - 1)
        s >>= 1
    return acc + d


def tile_range(z: int, bbox: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    west, south, east, north = bbox
    n = 1 << z

    def row(lat: float) -> int:
        rad = math.radians(max(min(lat, 85.0511), -85.0511))
        return int((1 - math.asinh(math.tan(rad)) / math.pi) / 2 * n)

    return (max(int((west + 180) / 360 * n), 0), max(row(north), 0),
            min(int((east + 180) / 360 * n), n - 1), min(row(south), n - 1))


def wanted_ids(bbox: tuple[float, float, float, float], max_zoom: int) -> array:
    ids = array("Q")
    for z in range(max_zoom + 1):
        left, top, right, bottom = tile_range(z, bbox)
        for x in range(left, right + 1):
            for y in range(top, bottom + 1):
                ids.append(tile_id(z, x, y))
    return array("Q", sorted(ids))


def _varint(data: bytes, position: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[position]
        position += 1
        value |= (byte & 0x7f) << shift
        if byte < 0x80:
            return value, position
        shift += 7


def _put_varint(output: bytearray, value: int) -> None:
    while value >= 0x80:
        output.append((value & 0x7f) | 0x80)
        value >>= 7
    output.append(value)


def read_directory(data: bytes) -> list[tuple[int, int, int, int]]:
    """Decode a directory into (tile id, run length, offset, length)."""
    count, position = _varint(data, 0)
    columns: list[list[int]] = []
    for _ in range(3):
        column = []
        for _ in range(count):
            value, position = _varint(data, position)
            column.append(value)
        columns.append(column)
    ids, runs, lengths = columns
    last = 0
    for index in range(count):
        ids[index] = last = last + ids[index]
    offsets = []
    for index in range(count):
        value, position = _varint(data, position)
        if value == 0 and index:
            offsets.append(offsets[-1] + lengths[index - 1])
        else:
            offsets.append(value - 1)
    return list(zip(ids, runs, offsets, lengths))


def write_directory(entries: list[tuple[int, int, int, int]]) -> bytes:
    output = bytearray()
    _put_varint(output, len(entries))
    last = 0
    for entry in entries:
        _put_varint(output, entry[0] - last)
        last = entry[0]
    for entry in entries:
        _put_varint(output, entry[1])
    for entry in entries:
        _put_varint(output, entry[3])
    for index, entry in enumerate(entries):
        follows = index and entry[2] == entries[index - 1][2] + entries[index - 1][3]
        _put_varint(output, 0 if follows else entry[2] + 1)
    return bytes(output)


def decompress(data: bytes, compression: int) -> bytes:
    if compression == GZIP:
        return gzip.decompress(data)
    if compression == 1:
        return data
    raise ValueError("This archive uses a compression SURVIVAL OS cannot read")


def compress(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


@dataclass
class Plan:
    """Tiles to copy. Runs are (tile id, run length, source offset, length), by tile id."""
    header: Header
    metadata: bytes
    runs: list[tuple[int, int, int, int]] = field(default_factory=list)

    @property
    def tile_bytes(self) -> int:
        return sum(length for _, length, _ in self.chunks())

    def chunks(self) -> list[tuple[int, int, int]]:
        """Each distinct tile once, as (source offset, length, new offset), in source order."""
        distinct = sorted({(run[2], run[3]) for run in self.runs})
        placed = []
        position = 0
        for offset, length in distinct:
            placed.append((offset, length, position))
            position += length
        return placed


def make_plan(reader: Reader, bbox: tuple[float, float, float, float], max_zoom: int,
              progress: Callable[[], None] = lambda: None) -> Plan:
    header = parse_header(reader.read(0, HEADER_BYTES))
    if not header.clustered:
        raise ValueError("The source archive is not clustered")
    max_zoom = min(max_zoom, header.max_zoom)
    wanted = wanted_ids(bbox, max_zoom)
    plan = Plan(header, decompress(reader.read(header.metadata_offset, header.metadata_length),
                                   header.internal_compression))

    def overlaps(first: int, past: int) -> bool:
        index = bisect_left(wanted, first)
        return index < len(wanted) and wanted[index] < past

    def walk(directory: list[tuple[int, int, int, int]]) -> None:
        for index, (first, run, offset, length) in enumerate(directory):
            past = directory[index + 1][0] if index + 1 < len(directory) else 1 << 62
            if run == 0:
                if overlaps(first, past):
                    progress()
                    raw = reader.read(header.leaf_offset + offset, length)
                    walk(read_directory(decompress(raw, header.internal_compression)))
                continue
            start = bisect_left(wanted, first)
            stop = bisect_left(wanted, first + run)
            for position in range(start, stop):
                tile = wanted[position]
                last = plan.runs[-1] if plan.runs else None
                if last and last[2] == offset and last[0] + last[1] == tile:
                    plan.runs[-1] = (last[0], last[1] + 1, offset, length)
                else:
                    plan.runs.append((tile, 1, offset, length))

    root = reader.read(header.root_offset, header.root_length)
    walk(read_directory(decompress(root, header.internal_compression)))
    return plan


def requests(chunks: list[tuple[int, int, int]]) -> Iterator[list[tuple[int, int, int]]]:
    """Group neighbouring tiles, so a region takes hundreds of requests rather than millions."""
    group: list[tuple[int, int, int]] = []
    for chunk in chunks:
        if group:
            start = group[0][0]
            end = group[-1][0] + group[-1][1]
            if chunk[0] - end > MERGE_GAP or chunk[0] + chunk[1] - start > MAX_REQUEST:
                yield group
                group = []
        group.append(chunk)
    if group:
        yield group


def check_tile(data: bytes, compression: int, tile_type: int = UNKNOWN) -> None:
    """Gzip carries a CRC, the only integrity record that exists for part of a world build."""
    if tile_type == WEBP:
        # WebP has no CRC by default, so its own length field is the check that remains.
        size = int.from_bytes(data[4:8], "little") + 8 if len(data) >= 12 else -1
        if data[:4] != b"RIFF" or data[8:12] != b"WEBP" or size > len(data):
            raise ValueError("A map tile arrived damaged")
    elif compression == GZIP:
        stream = zlib.decompressobj(wbits=31)
        stream.decompress(data)
        if not stream.eof:
            raise ValueError("A map tile arrived damaged")


def download_tiles(reader: Reader, plan: Plan, output: BinaryIO, done: int,
                   progress: Callable[[int], None] = lambda _: None) -> None:
    """Append tiles after the `done` bytes already written. `done` must sit on a tile edge."""
    base = plan.header.tile_offset
    todo = [chunk for chunk in plan.chunks() if chunk[2] >= done]
    for group in requests(todo):
        start = group[0][0]
        data = reader.read(base + start, group[-1][0] + group[-1][1] - start)
        for offset, length, _ in group:
            tile = data[offset - start:offset - start + length]
            try:
                check_tile(tile, plan.header.tile_compression, plan.header.tile_type)
            except zlib.error as error:
                raise ValueError("A map tile arrived damaged") from error
            output.write(tile)
            done += length
        progress(done)


def tile_edge(plan: Plan, size: int) -> int:
    """The largest tile boundary at or below `size`, so a torn write is dropped on resume."""
    edge = 0
    for _, length, position in plan.chunks():
        if position + length > size:
            break
        edge = position + length
    return edge


def _directories(entries: list[tuple[int, int, int, int]]) -> tuple[bytes, bytes]:
    root = compress(write_directory(entries))
    if len(root) + HEADER_BYTES <= ROOT_BYTES:
        return root, b""
    leaf_size = LEAF_SIZE
    while True:
        leaves = bytearray()
        index = []
        for start in range(0, len(entries), leaf_size):
            part = entries[start:start + leaf_size]
            data = compress(write_directory(part))
            index.append((part[0][0], 0, len(leaves), len(data)))
            leaves += data
        root = compress(write_directory(index))
        if len(root) + HEADER_BYTES <= ROOT_BYTES:
            return root, bytes(leaves)
        leaf_size *= 2


def finish(plan: Plan, path: Path, bbox: tuple[float, float, float, float], max_zoom: int) -> None:
    """Write the directories and the real header into the part file holding the tiles."""
    moved = {(chunk[0], chunk[1]): chunk[2] for chunk in plan.chunks()}
    entries = [(tile, run, moved[(offset, length)], length)
               for tile, run, offset, length in plan.runs]
    root, leaves = _directories(entries)
    tile_length = plan.tile_bytes
    metadata = compress(plan.metadata or b"{}")
    west, south, east, north = bbox
    source = plan.header
    header = Header(
        root_offset=HEADER_BYTES, root_length=len(root),
        metadata_offset=ROOT_BYTES + tile_length, metadata_length=len(metadata),
        leaf_offset=ROOT_BYTES + tile_length + len(metadata), leaf_length=len(leaves),
        tile_offset=ROOT_BYTES, tile_length=tile_length,
        addressed_tiles=sum(entry[1] for entry in entries), tile_entries=len(entries),
        tile_contents=len(moved), clustered=True, internal_compression=GZIP,
        tile_compression=source.tile_compression, tile_type=source.tile_type,
        min_zoom=0, max_zoom=min(max_zoom, source.max_zoom),
        bounds=tuple(round(value * 10_000_000) for value in (west, south, east, north)),
        center_zoom=min(max_zoom, 8),
        center=(round((west + east) * 5_000_000), round((south + north) * 5_000_000)))
    with path.open("r+b") as output:
        output.seek(ROOT_BYTES + tile_length)
        output.truncate()
        output.write(metadata)
        output.write(leaves)
        output.flush()
        output.seek(0)
        output.write(pack_header(header))
        output.write(root)


def check_archive(path: Path) -> int:
    """Walk every directory and prove each entry lies inside the tile section. Returns tiles."""
    with path.open("rb") as handle:
        header = parse_header(handle.read(HEADER_BYTES))

        def read(offset: int, length: int) -> bytes:
            handle.seek(offset)
            data = handle.read(length)
            if len(data) != length:
                raise ValueError("The map file is cut short")
            return data

        def walk(raw: bytes) -> int:
            count = 0
            for _, run, offset, length in read_directory(decompress(raw, GZIP)):
                if run == 0:
                    count += walk(read(header.leaf_offset + offset, length))
                else:
                    if offset + length > header.tile_length:
                        raise ValueError("A map directory points outside the file")
                    count += run
            return count

        addressed = walk(read(header.root_offset, header.root_length))
        json.loads(decompress(read(header.metadata_offset, header.metadata_length), GZIP))
    if addressed != header.addressed_tiles:
        raise ValueError("The map directory does not match its header")
    return addressed


class TileFile:
    """Read single tiles from an installed archive, for clients that need plain tile URLs."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.stamp = path.stat().st_mtime_ns
        with path.open("rb") as handle:
            self.header = parse_header(handle.read(HEADER_BYTES))
            handle.seek(self.header.root_offset)
            self.root = read_directory(decompress(handle.read(self.header.root_length), GZIP))
        self.leaves: dict[int, list[tuple[int, int, int, int]]] = {}

    def _leaf(self, handle: BinaryIO, offset: int, length: int) -> list:
        if offset not in self.leaves:
            if len(self.leaves) >= 64:
                self.leaves.pop(next(iter(self.leaves)))
            handle.seek(self.header.leaf_offset + offset)
            self.leaves[offset] = read_directory(decompress(handle.read(length), GZIP))
        return self.leaves[offset]

    def tile(self, z: int, x: int, y: int) -> bytes | None:
        key = tile_id(z, x, y)
        directory = self.root
        with self.path.open("rb") as handle:
            for _ in range(4):
                index = bisect_left(directory, (key + 1,)) - 1
                if index < 0:
                    return None
                first, run, offset, length = directory[index]
                if run == 0:
                    directory = self._leaf(handle, offset, length)
                    continue
                if key >= first + run:
                    return None
                handle.seek(self.header.tile_offset + offset)
                return handle.read(length)
        return None
