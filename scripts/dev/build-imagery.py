#!/usr/bin/env python3
"""Build a PMTiles aerial photo map from the USGS NAIP image service, on the dev machine.

    build-imagery.py fetch WORK --boxes BOXES.json --zoom 16
    build-imagery.py build WORK OUTPUT.pmtiles --title "Wake County aerial photos"

BOXES.json is a list of [west, south, east, north], such as one per county. Fetch keeps each block in WORK, so a stopped run resumes. Two requests at a time, to be polite.
"""

import argparse
import io
import json
import math
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from survival_os import pmtiles  # noqa: E402

SERVICE = ("https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer"
           "/exportImage")
EDGE = 20037508.342789244
BLOCK_TILES = 8
TILE = 256
QUALITY = 72
LOWEST_ZOOM = 8
WORKERS = 2
RETRIES = 6
JPEG = 3


def block_url(zoom: int, x: int, y: int) -> str:
    span = 2 * EDGE / (1 << zoom)
    left, top = -EDGE + x * span, EDGE - y * span
    box = f"{left},{top - BLOCK_TILES * span},{left + BLOCK_TILES * span},{top}"
    size = BLOCK_TILES * TILE
    return (f"{SERVICE}?bbox={box}&bboxSR=3857&imageSR=3857&size={size},{size}"
            "&format=jpg&f=image")


def fetch_block(work: Path, zoom: int, x: int, y: int) -> None:
    target = work / f"{x}_{y}.jpg"
    if target.exists():
        return
    for attempt in range(RETRIES):
        try:
            request = urllib.request.Request(block_url(zoom, x, y), headers={
                "User-Agent": "SURVIVAL-OS-imagery-build"})
            with urllib.request.urlopen(request, timeout=180) as response:
                data = response.read()
            Image.open(io.BytesIO(data)).verify()
            temporary = target.with_suffix(".part")
            temporary.write_bytes(data)
            temporary.replace(target)
            return
        except OSError as error:
            print(f"retry {x},{y}: {error}", flush=True)
            time.sleep(10 * (attempt + 1))
    raise OSError(f"Block {x},{y} kept failing")


def fetch(args: argparse.Namespace) -> None:
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    boxes = json.loads(Path(args.boxes).read_text())
    (work / "job.json").write_text(json.dumps({"boxes": boxes, "zoom": args.zoom}))
    found = set()
    for box in boxes:
        left, top, right, bottom = pmtiles.tile_range(args.zoom, tuple(box))
        found |= {(x, y) for x in range(left - left % BLOCK_TILES, right + 1, BLOCK_TILES)
                  for y in range(top - top % BLOCK_TILES, bottom + 1, BLOCK_TILES)}
    blocks = sorted(found)
    print(f"{len(blocks)} blocks", flush=True)
    start = time.time()

    def one(index_block):
        index, (x, y) = index_block
        fetch_block(work, args.zoom, x, y)
        if index % 10 == 0:
            print(f"{index}/{len(blocks)} {time.time() - start:.0f}s", flush=True)

    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, enumerate(blocks)))
    print(f"done in {time.time() - start:.0f}s", flush=True)


def encode(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.convert("RGB").save(output, "JPEG", quality=QUALITY, optimize=True)
    return output.getvalue()


def build(args: argparse.Namespace) -> None:
    work = Path(args.work)
    job = json.loads((work / "job.json").read_text())
    zoom, boxes = job["zoom"], job["boxes"]
    bbox = (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))
    # Only encoded tiles stay in memory. A few hundred blocks of raw pixels would not fit.
    tiles: dict[int, bytes] = {}
    level: set[tuple[int, int]] = set()
    for path in sorted(work.glob("*.jpg")):
        bx, by = (int(part) for part in path.stem.split("_"))
        with Image.open(path) as block:
            block.load()
            for dx in range(BLOCK_TILES):
                for dy in range(BLOCK_TILES):
                    box = (dx * TILE, dy * TILE, (dx + 1) * TILE, (dy + 1) * TILE)
                    level.add((bx + dx, by + dy))
                    tiles[pmtiles.tile_id(zoom, bx + dx, by + dy)] = encode(block.crop(box))
    for z in range(zoom - 1, LOWEST_ZOOM - 1, -1):
        parents = {(x // 2, y // 2) for x, y in level}
        for px, py in parents:
            parent = Image.new("RGB", (TILE, TILE), "white")
            for dx in (0, 1):
                for dy in (0, 1):
                    child = tiles.get(pmtiles.tile_id(z + 1, px * 2 + dx, py * 2 + dy))
                    if child:
                        with Image.open(io.BytesIO(child)) as tile:
                            half = tile.resize((TILE // 2, TILE // 2), Image.Resampling.LANCZOS)
                        parent.paste(half, (dx * TILE // 2, dy * TILE // 2))
            tiles[pmtiles.tile_id(z, px, py)] = encode(parent)
        level = parents

    runs = []
    position = 0
    output = Path(args.output)
    with output.open("wb") as handle:
        handle.write(bytes(pmtiles.ROOT_BYTES))
        for key in sorted(tiles):
            data = tiles[key]
            handle.write(data)
            runs.append((key, 1, position, len(data)))
            position += len(data)
    header = pmtiles.parse_header(pmtiles.pack_header(pmtiles.Header(
        0, 0, 0, 0, 0, 0, 0, position, 0, 0, 0, True, pmtiles.GZIP, 1, JPEG, LOWEST_ZOOM, zoom,
        (0, 0, 0, 0), 0, (0, 0))))
    metadata = json.dumps({"name": args.title, "attribution": "USDA NAIP, USGS"}).encode()
    pmtiles.finish(pmtiles.Plan(header, metadata, runs), output, bbox, zoom)
    print(f"{len(tiles)} tiles, {output.stat().st_size / 1e9:.2f} GB, by zoom:")
    print(pmtiles.check_archive(output), "addressed")
    for z in range(LOWEST_ZOOM, zoom + 1):
        first = (4 ** z - 1) // 3
        size = sum(len(data) for key, data in tiles.items() if first <= key < first + 4 ** z)
        print(z, f"{size / 1e9:.2f} GB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    get = commands.add_parser("fetch")
    get.add_argument("work")
    get.add_argument("--boxes", required=True)
    get.add_argument("--zoom", type=int, default=16)
    get.set_defaults(run=fetch)
    make = commands.add_parser("build")
    make.add_argument("work")
    make.add_argument("output")
    make.add_argument("--title", required=True)
    make.set_defaults(run=build)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
