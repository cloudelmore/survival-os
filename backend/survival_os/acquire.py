"""Content worker. The only part of SURVIVAL OS that may use the network.

systemd starts it when the user asks for an acquisition. It works through the queue and exits, so
nothing stays online afterwards. Downloads resume from a .part file, and the whole file, resumed
bytes included, is checked against the published SHA-256 before it is installed.
"""

import hashlib
import http.client
import fnmatch
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from . import content, pmtiles
from .content import Paths, Refused

log = logging.getLogger("survival-content")

BLOCK = 1024 * 1024
TIMEOUT = 60
RETRIES = 5
RETRY_WAIT = 15
PROGRESS_INTERVAL = 2
USER_AGENT = "SURVIVAL-OS-content-manager"
MAX_UNPACKED_FILE = 64 * 1024 * 1024
METALINK = {"m": "urn:ietf:params:xml:ns:metalink"}
OPDS = {"a": "http://www.w3.org/2005/Atom"}
CATALOG_URL = "https://opds.library.kiwix.org/catalog/v2/entries"
MAP_BUILDS_URL = "https://build-metadata.protomaps.dev/builds.json"
MAP_BUILD_BASE = "https://build.protomaps.com/"
# The bundled map style reads this version of the tile layout.
MAP_SCHEMA_MAJOR = "4"


class Stop(Exception):
    """The user cancelled. The partial file stays, so a later install resumes it."""


@dataclass
class Source:
    url: str
    size: int | None
    sha256: str | None
    checksum_source: str


def fetch(url: str, headers: dict | None = None):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


class RangeReader:
    """Byte ranges over one kept-alive connection. A region needs hundreds of them."""

    def __init__(self, url: str) -> None:
        parts = urlsplit(url)
        self.host, self.path = parts.netloc, parts.path
        self.secure = parts.scheme == "https"
        self.connection: http.client.HTTPConnection | None = None

    def _connect(self) -> http.client.HTTPConnection:
        kind = http.client.HTTPSConnection if self.secure else http.client.HTTPConnection
        return kind(self.host, timeout=TIMEOUT)

    def read(self, offset: int, length: int) -> bytes:
        failure: Exception | None = None
        for attempt in range(RETRIES):
            if attempt:
                time.sleep(RETRY_WAIT)
            try:
                self.connection = self.connection or self._connect()
                self.connection.request("GET", self.path, headers={
                    "User-Agent": USER_AGENT, "Range": f"bytes={offset}-{offset + length - 1}"})
                response = self.connection.getresponse()
                data = response.read()
                if response.status == 206 and len(data) == length:
                    return data
                failure = ConnectionError(f"Map server answered {response.status}")
            except (http.client.HTTPException, OSError) as error:
                failure = error
            log.warning("Map range attempt %d failed: %s", attempt + 1, failure)
            if self.connection:
                self.connection.close()
            self.connection = None
        raise ConnectionError(f"The map server kept failing: {failure}")


def latest_map_build() -> dict:
    """The newest world build. Old ones are deleted within days, so none can be pinned."""
    with fetch(MAP_BUILDS_URL) as response:
        builds = json.loads(response.read())
    usable = [item for item in builds
              if item["key"].endswith(".pmtiles")
              and str(item.get("version", "")).split(".")[0] == MAP_SCHEMA_MAJOR]
    if not usable:
        raise Refused("No world map build matches this version of SURVIVAL OS")
    newest = max(usable, key=lambda item: item["key"])
    return {"version": newest["key"].removesuffix(".pmtiles"),
            "url": MAP_BUILD_BASE + newest["key"]}


def latest_extract(entry: dict) -> dict:
    """Where a map region comes from: a named archive, or else the newest daily build."""
    source = entry["extract"].get("source")
    if not source:
        return latest_map_build()
    with fetch(entry["extract"]["version_url"]) as response:
        return {"version": str(json.loads(response.read())["version"]), "url": source}


def resolve_source(entry: dict) -> Source:
    """Read the size and checksum live, instead of trusting what the manifest recorded."""
    url = entry["source_url"]["value"]
    if url.endswith(".meta4"):
        with fetch(url) as response:
            root = ET.fromstring(response.read())
        hashes = root.findall(".//m:file/m:hash[@type='sha-256']", METALINK)
        size = root.findtext(".//m:file/m:size", namespaces=METALINK)
        if not hashes or size is None:
            raise Refused("The publisher's download record has no checksum")
        return Source(url.removesuffix(".meta4"), int(size), hashes[0].text.strip(),
                      "published (meta4)")
    pinned = entry["sha256"]["value"]
    return Source(url, entry["size_bytes"]["value"], pinned,
                  "manifest" if pinned else "none published")


class Worker:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.db = content.connect(paths)

    def update_job(self, job_id: int, **values) -> None:
        columns = ", ".join(f"{name}=?" for name in values)
        self.db.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*values.values(), job_id))
        self.db.commit()

    def stopped(self, job_id: int) -> bool:
        row = self.db.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
        return row["state"] == "cancelling"

    def _transfer(self, job_id: int, source: Source, part: Path) -> None:
        done = part.stat().st_size if part.exists() else 0
        if source.size is not None and done > source.size:
            part.unlink()
            done = 0
        if source.size is not None and done == source.size:
            return
        headers = {"Range": f"bytes={done}-"} if done else {}
        with fetch(source.url, headers) as response:
            if done and response.status != 206:
                # The server ignored the range, so starting over is the only honest option.
                done = 0
            if response.status == 206:
                total = int(response.headers["Content-Range"].split("/")[-1])
            else:
                # Generated archives have no length, so the checksum alone proves them.
                total = int(response.headers.get("Content-Length") or source.size or 0)
            if source.size is not None and total != source.size:
                raise Refused("The server's file size does not match the publisher's record")
            last = 0.0
            with part.open("ab" if done else "wb") as output:
                while block := response.read(BLOCK):
                    output.write(block)
                    done += len(block)
                    if time.monotonic() - last >= PROGRESS_INTERVAL:
                        last = time.monotonic()
                        output.flush()
                        self.update_job(job_id, bytes_done=done, bytes_total=total)
                        if self.stopped(job_id):
                            raise Stop
                        # Other writes, such as indexing, can use the room while this runs.
                        if total - done > content.capacity(self.paths.state)["headroom"]:
                            raise Refused("Stopped at the 15% free floor. Free some space and"
                                          " install again to resume")
        self.update_job(job_id, bytes_done=done)
        # A dropped connection can look like a normal end of stream.
        if done < total:
            raise ConnectionError("The connection closed early")

    def download(self, job_id: int, source: Source, part: Path) -> None:
        for attempt in range(1, RETRIES + 1):
            try:
                self._transfer(job_id, source, part)
                return
            except urllib.error.HTTPError as error:
                if error.code == 416:
                    part.unlink(missing_ok=True)
                    continue
                failure = error
            except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
                failure = error
            log.warning("Download attempt %d failed: %s", attempt, failure)
            if self.stopped(job_id):
                raise Stop
            time.sleep(RETRY_WAIT)
        raise Refused("The download kept failing. Try again, and it will resume")

    def install(self, job_id: int, entry: dict, version: str | None = None,
                url: str | None = None) -> None:
        category = entry["budget_category"]
        if entry.get("extract"):
            self.install_map(job_id, entry, version, url)
            return
        if url:
            entry = {**entry, "source_url": {**entry["source_url"], "value": url}}
        self.update_job(job_id, phase="checking source")
        source = resolve_source(entry)
        final = content.destination(self.paths, entry)
        part = self.paths.partial / f"{final.name}.part"
        part.parent.mkdir(parents=True, exist_ok=True)
        size = source.size or entry["size_bytes"]["value"] or 0
        have = part.stat().st_size if part.exists() else 0
        replaced = self.current_bytes(entry["id"])
        content.check(self.paths, category, max(size - have, 0), max(size - replaced, 0))

        self.update_job(job_id, phase="downloading", bytes_total=size, bytes_done=have)
        self.download(job_id, source, part)

        self.update_job(job_id, phase="verifying")
        digest = sha256_file(part)
        if source.sha256 and digest != source.sha256:
            part.unlink()
            raise Refused("Checksum failed, so the file was discarded")
        final.parent.mkdir(parents=True, exist_ok=True)

        self.update_job(job_id, phase="installing")
        old = self.db.execute("SELECT path FROM installed WHERE id=?", (entry["id"],)).fetchone()
        if entry.get("archive"):
            unpack(part, final, entry["archive"]["keep"])
            part.unlink()
        else:
            os.replace(part, final)
        if old and self.paths.state / old["path"] != final:
            delete_path(self.paths.state / old["path"])
        self.record(entry["id"], entry["title"], entry["format"], category, final, digest,
                    version or entry["publication_date"]["value"] or "unknown",
                    source.url, source.checksum_source)
        self.db.execute("DELETE FROM updates WHERE id=?", (entry["id"],))
        self.db.commit()
        self.refresh_kiwix()

    def install_map(self, job_id: int, entry: dict, version: str | None,
                    url: str | None) -> None:
        """Cut one region out of the newest world build, resuming from the part file."""
        category = entry["budget_category"]
        bbox = tuple(entry["extract"]["bbox"])
        max_zoom = entry["extract"]["max_zoom"]
        self.update_job(job_id, phase="finding the newest map")
        final = content.destination(self.paths, entry)
        part = self.paths.partial / f"{final.name}.part"
        note = part.with_suffix(".json")
        part.parent.mkdir(parents=True, exist_ok=True)
        # A part file holds tiles from one build, so finish that build while it still exists.
        saved = json.loads(note.read_text()) if note.exists() and part.exists() else None
        chosen = saved if saved else (
            {"version": version, "url": url} if url else latest_extract(entry))
        self.update_job(job_id, phase="reading the world index")
        reader = RangeReader(chosen["url"])
        try:
            plan = pmtiles.make_plan(reader, bbox, max_zoom)
        except ConnectionError:
            if not saved:
                raise
            # That build has gone, and its tiles cannot be mixed with another.
            part.unlink()
            note.unlink()
            chosen = latest_extract(entry)
            saved = None
            reader = RangeReader(chosen["url"])
            plan = pmtiles.make_plan(reader, bbox, max_zoom)
        total = plan.tile_bytes
        done = pmtiles.tile_edge(plan, max(part.stat().st_size - pmtiles.ROOT_BYTES, 0)) \
            if saved else 0
        replaced = self.current_bytes(entry["id"])
        content.check(self.paths, category, total - done, max(total - replaced, 0))
        if not saved:
            with part.open("wb") as output:
                output.write(bytes(pmtiles.ROOT_BYTES))
            note.write_text(json.dumps(chosen))

        self.update_job(job_id, phase="downloading", bytes_total=total, bytes_done=done)

        def progress(written: int) -> None:
            self.update_job(job_id, bytes_done=written)
            if self.stopped(job_id):
                raise Stop
            if total - written > content.capacity(self.paths.state)["headroom"]:
                raise Refused("Stopped at the 15% free floor. Free some space and"
                              " install again to resume")

        with part.open("r+b") as output:
            output.truncate(pmtiles.ROOT_BYTES + done)
            output.seek(pmtiles.ROOT_BYTES + done)
            pmtiles.download_tiles(reader, plan, output, done, progress)

        self.update_job(job_id, phase="verifying")
        pmtiles.finish(plan, part, bbox, max_zoom)
        pmtiles.check_archive(part)
        digest = sha256_file(part)
        final.parent.mkdir(parents=True, exist_ok=True)
        self.update_job(job_id, phase="installing")
        os.replace(part, final)
        note.unlink()
        self.record(entry["id"], entry["title"], entry["format"], category, final, digest,
                    chosen["version"], chosen["url"], "tiles checked, computed after download")
        self.db.execute("DELETE FROM updates WHERE id=?", (entry["id"],))
        self.db.commit()

    def current_bytes(self, entry_id: str) -> int:
        row = self.db.execute("SELECT bytes FROM installed WHERE id=?", (entry_id,)).fetchone()
        return row["bytes"] if row else 0

    def record(self, entry_id: str, title: str, fmt: str, category: str, path: Path, digest: str,
               version: str, origin: str, checksum_source: str) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO installed (id, title, format, category, path, bytes, sha256,"
            " version, origin, checksum_source, installed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (entry_id, title, fmt, category, content.stored_path(self.paths, path),
             content.tree_bytes(path) if path.is_dir() else path.stat().st_size, digest, version,
             origin, checksum_source, time.time()))
        self.db.commit()

    def remove(self, entry_id: str) -> None:
        row = self.db.execute("SELECT path FROM installed WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise Refused("That collection is not installed")
        delete_path(self.paths.state / row["path"])
        self.db.execute("DELETE FROM installed WHERE id=?", (entry_id,))
        self.db.execute("DELETE FROM updates WHERE id=?", (entry_id,))
        self.db.commit()
        for part in self.paths.partial.glob("*.part") if self.paths.partial.is_dir() else ():
            if part.name == f"{Path(row['path']).name}.part":
                part.unlink()
                part.with_suffix(".json").unlink(missing_ok=True)
        self.refresh_kiwix()

    def validate(self, job_id: int, entry_id: str) -> None:
        row = self.db.execute("SELECT * FROM installed WHERE id=?", (entry_id,)).fetchone()
        if row is None:
            raise Refused("That collection is not installed")
        self.update_job(job_id, phase="verifying", bytes_total=row["bytes"])
        path = self.paths.state / row["path"]
        # An unpacked archive has no file to hash, so its checksum only applied at download.
        if path.is_dir() and any(path.iterdir()):
            return
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise Refused("This collection is damaged. Remove it and install it again")

    def check_updates(self) -> None:
        for key, entry in content.load_catalog(self.paths).items():
            source = entry.get("kiwix")
            row = self.db.execute("SELECT version FROM installed WHERE id=?", (key,)).fetchone()
            if row is None or not (source or entry.get("extract")):
                continue
            if source:
                found = latest_kiwix(source["name"], source.get("flavour", ""))
            else:
                found = {**latest_extract(entry), "bytes": entry["size_bytes"]["value"] or 0}
            if found and found["version"] > row["version"]:
                self.db.execute("INSERT OR REPLACE INTO updates VALUES (?, ?, ?, ?)",
                                (key, found["version"], found["url"], found["bytes"]))
                self.db.commit()

    def refresh_kiwix(self) -> None:
        """Rebuild the Kiwix library file. kiwix-serve watches it and picks up the change."""
        rows = self.db.execute("SELECT path FROM installed WHERE format='zim'").fetchall()
        manage = shutil.which("kiwix-manage")
        if manage is None:
            return
        temporary = self.paths.kiwix_library.with_suffix(".new.xml")
        temporary.write_text(content.EMPTY_KIWIX_LIBRARY)
        for row in rows:
            subprocess.run([manage, str(temporary), "add", str(self.paths.state / row["path"])],
                           check=True, capture_output=True, timeout=120)
        temporary.replace(self.paths.kiwix_library)

    def run_job(self, job: sqlite3.Row) -> None:
        job_id, action, target = job["id"], job["action"], job["target"]
        self.update_job(job_id, state="running", error=None)
        try:
            catalog = content.load_catalog(self.paths)
            if action == "install":
                self.install(job_id, catalog[target])
            elif action == "update":
                update = self.db.execute("SELECT * FROM updates WHERE id=?", (target,)).fetchone()
                if update is None:
                    raise Refused("No update is waiting")
                self.install(job_id, catalog[target], update["version"], update["source_url"])
            elif action == "remove":
                self.remove(target)
            elif action == "validate":
                self.validate(job_id, target)
            elif action == "check-updates":
                self.check_updates()
            elif action == "import":
                from .removable import import_file
                import_file(self, job_id, target)
            self.update_job(job_id, state="done", phase="")
        except Stop:
            self.update_job(job_id, state="cancelled", phase="")
        except (Refused, KeyError) as error:
            self.update_job(job_id, state="failed", phase="", error=str(error))
        except (OSError, subprocess.SubprocessError, ET.ParseError, ValueError) as error:
            log.exception("Job %d failed", job_id)
            self.update_job(job_id, state="failed", phase="", error=f"Failed: {error}")

    def run(self) -> None:
        # A power cut leaves a job marked running. Its partial file lets it pick up where it was.
        self.db.execute("UPDATE jobs SET state='queued' WHERE state='running'")
        self.db.execute("UPDATE jobs SET state='cancelled' WHERE state='cancelling'")
        self.db.commit()
        while job := self.db.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY id LIMIT 1").fetchone():
            self.run_job(job)


def delete_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def tidy_markdown(text: str) -> str:
    """Turn website MDX into plain Markdown: keep the title, drop site code and components."""
    title = ""
    if text.startswith("---"):
        front, _, text = text[3:].partition("\n---")
        match = re.search(r"^title:\s*(.+)$", front, re.MULTILINE)
        title = match.group(1).strip("\"' ") if match else ""
    lines = [line for line in text.splitlines()
             if not re.match(r"\s*(import|export)\s", line)
             and not re.match(r"\s*</?[A-Z][^>]*/?>\s*$", line)]
    body = "\n".join(lines).strip()
    return f"# {title}\n\n{body}\n" if title else f"{body}\n"


def unpack(archive: Path, target: Path, keep: list[str]) -> None:
    """Extract only the wanted files. A repository archive holds one top-level folder."""
    temporary = target.with_name(f".{target.name}.new")
    delete_path(temporary)
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            parts = PurePosixPath(info.filename).parts[1:]
            name = "/".join(parts)
            if info.is_dir() or ".." in parts or info.file_size > MAX_UNPACKED_FILE \
                    or not any(fnmatch.fnmatch(name, pattern) for pattern in keep):
                continue
            output = temporary.joinpath(*parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            data = bundle.read(info)
            if output.suffix == ".mdx":
                output = output.with_suffix(".md")
            if output.suffix == ".md":
                output.write_text(tidy_markdown(data.decode("utf-8", "replace")))
            else:
                output.write_bytes(data)
    delete_path(target)
    temporary.replace(target)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(BLOCK):
            digest.update(block)
    return digest.hexdigest()


def latest_kiwix(name: str, flavour: str) -> dict | None:
    with fetch(f"{CATALOG_URL}?name={name}&count=20") as response:
        root = ET.fromstring(response.read())
    for item in root.findall("a:entry", OPDS):
        if (item.findtext("a:flavour", "", OPDS) or "") != flavour:
            continue
        link = next((l for l in item.findall("a:link", OPDS) if l.get("length")), None)
        if link is not None:
            return {"version": item.findtext("a:updated", "", OPDS)[:10], "url": link.get("href"),
                    "bytes": int(link.get("length"))}
    return None


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    Worker(Paths.from_env()).run()


if __name__ == "__main__":
    main()
