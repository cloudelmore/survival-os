"""Search the index and report on it. Everything here reads the database and changes nothing."""

import json
import re
import sqlite3

from . import store
from .indexer import Paths

HIT_START, HIT_END = "", ""
MAX_TERMS = 12
# Enough to rank well without letting a very common word scan the whole library on the Pi.
MAX_MATCHES = 5000
PASSAGE_CHARS = 900
# Enough of a word to match its plural or verb form.
STEM = 6
QUESTION_WORDS = frozenset("""
a about after all am an and any are as at be been but by can could did do does for from get had has
have how i if in into is it its me my no not of on or our should so some than that the their them
then there these they this to us was we were what when where which who why will with would you your
""".split())
TERM = re.compile(r'"([^"]+)"|(\S+)')
WORD = re.compile(r"\w+")


def match_expression(text: str) -> str | None:
    """Build an FTS5 query from user text. Terms are quoted, so none of it acts as FTS5 syntax."""
    terms = []
    for phrase, word in TERM.findall(text)[:MAX_TERMS]:
        words = WORD.findall(phrase or word)
        if words:
            terms.append('"' + " ".join(words) + '"')
    if not terms:
        return None
    if not text.rstrip().endswith('"'):
        terms[-1] += "*"
    return " ".join(terms)


def split_snippet(snippet: str) -> list[dict]:
    """Return plain segments, so the viewer never has to treat indexed text as markup."""
    segments = []
    for index, part in enumerate(re.split(f"[{HIT_START}{HIT_END}]", snippet)):
        if part:
            segments.append({"text": part, "hit": index % 2 == 1})
    return segments


def search(paths: Paths, text: str, fmt: str | None = None, category: str | None = None,
           limit: int = 20, offset: int = 0) -> dict:
    empty = {"results": [], "total": 0, "more": False}
    expression = match_expression(text)
    db = store.connect_readonly(paths.database)
    if expression is None or db is None:
        return empty
    with db:
        filters, parameters = "", [expression]
        if fmt:
            filters += " AND d.format=?"
            parameters.append(fmt)
        if category:
            filters += " AND d.category=?"
            parameters.append(category)
        # One result per location: a location split into passages must not fill the page.
        rows = db.execute(
            f"""
            WITH matched AS (
                SELECT f.rowid AS id, f.rank AS score, p.document_id, p.page
                FROM passages_fts f
                JOIN passages p ON p.id = f.rowid
                JOIN documents d ON d.id = p.document_id
                WHERE passages_fts MATCH ?{filters}
                ORDER BY f.rank LIMIT {MAX_MATCHES}
            ), best AS (
                SELECT *, row_number() OVER (PARTITION BY document_id, page ORDER BY score) AS n
                FROM matched
            )
            SELECT id, count(*) OVER () AS total FROM best WHERE n = 1
            ORDER BY score LIMIT ? OFFSET ?
            """,
            [*parameters, limit, offset],
        ).fetchall()
        if not rows:
            return empty
        ids = [row["id"] for row in rows]
        marks = ",".join("?" * len(ids))
        details = {row["id"]: row for row in db.execute(
            f"""
            SELECT f.rowid AS id, p.page, p.label, d.id AS document_id, d.title, d.format,
                   d.category, d.path, d.pages_total,
                   snippet(passages_fts, 0, '{HIT_START}', '{HIT_END}', '…', 40) AS snippet
            FROM passages_fts f
            JOIN passages p ON p.id = f.rowid
            JOIN documents d ON d.id = p.document_id
            WHERE passages_fts MATCH ? AND f.rowid IN ({marks})
            """,
            [expression, *ids],
        )}
    total = rows[0]["total"]
    results = []
    for passage_id in ids:
        row = details[passage_id]
        segments = split_snippet(row["snippet"])
        results.append({
            "document_id": row["document_id"], "title": row["title"], "format": row["format"],
            "category": row["category"], "path": row["path"], "page": row["page"],
            "label": row["label"], "pages_total": row["pages_total"], "snippet": segments,
            "hits": sorted({s["text"].lower() for s in segments if s["hit"]}),
        })
    return {"results": results, "total": total, "more": offset + len(results) < total}


def query_words(text: str) -> list[str]:
    words = dict.fromkeys(word for word in WORD.findall(text.lower())
                          if word not in QUESTION_WORDS)
    return list(words)[:MAX_TERMS]


def question_expression(text: str) -> str | None:
    """Any word may match, unlike a search, because a question holds words no passage repeats."""
    return " OR ".join(f'"{word}"' for word in query_words(text)) or None


def passages(paths: Paths, text: str, limit: int = 4) -> list[dict]:
    """The best passages for a question, in full, at most one per page."""
    expression = question_expression(text)
    db = store.connect_readonly(paths.database)
    if expression is None or db is None:
        return []
    with db:
        rows = db.execute(
            """
            SELECT p.page, p.label, p.text, d.id AS document_id, d.title, d.format, d.category
            FROM (SELECT rowid AS id, rank AS score FROM passages_fts
                  WHERE passages_fts MATCH ? ORDER BY rank LIMIT 200) m
            JOIN passages p ON p.id = m.id
            JOIN documents d ON d.id = p.document_id
            ORDER BY m.score
            """, (expression,)).fetchall()
    words = query_words(text)
    found, seen = [], set()
    for row in rows:
        location = (row["document_id"], row["page"])
        if location in seen:
            continue
        seen.add(location)
        lowered = row["text"].lower()
        matched = sum(word[:STEM] in lowered for word in words)
        if matched * 2 > len(words):
            found.append((-matched, len(found), {**dict(row), "text": row["text"][:PASSAGE_CHARS]}))
    # Passages that share most of the question come first, then the search engine's order.
    return [row for _, _, row in sorted(found, key=lambda item: item[:2])[:limit]]


def status(paths: Paths) -> dict:
    report = {"documents": 0, "passages": 0, "pages_total": 0, "pages_done": 0, "pending": 0,
              "failed": [], "formats": {}, "categories": {}, "no_text": [],
              "indexer": {"state": "stopped", "detail": ""}}
    try:
        indexer = json.loads(paths.status_file.read_text())
        report["indexer"] = {"state": indexer["state"], "detail": indexer["detail"]}
    except (OSError, ValueError, KeyError):
        pass
    db = store.connect_readonly(paths.database)
    if db is None:
        return report
    with db:
        try:
            for row in db.execute(
                    "SELECT state, count(*) AS n, sum(pages_total) AS total,"
                    " sum(pages_done) AS done FROM documents GROUP BY state"):
                report["documents"] += row["n"]
                report["pages_total"] += row["total"] or 0
                report["pages_done"] += row["done"] or 0
                if row["state"] in ("pending", "indexing"):
                    report["pending"] += row["n"]
            report["formats"] = dict(db.execute(
                "SELECT format, count(*) FROM documents GROUP BY format").fetchall())
            report["categories"] = dict(db.execute(
                "SELECT category, count(*) FROM documents GROUP BY category").fetchall())
            report["failed"] = [dict(row) for row in db.execute(
                "SELECT path, error FROM documents WHERE state='failed' ORDER BY path LIMIT 50")]
            report["no_text"] = [dict(row) for row in db.execute(
                "SELECT path, pages_no_text FROM documents WHERE pages_no_text > 0"
                " ORDER BY pages_no_text DESC LIMIT 50")]
            report["passages"] = db.execute("SELECT count(*) FROM passages").fetchone()[0]
        except sqlite3.OperationalError:
            pass
    return report


def document(paths: Paths, document_id: int) -> dict | None:
    db = store.connect_readonly(paths.database)
    if db is None:
        return None
    with db:
        row = db.execute(
            "SELECT id, path, title, format, category, size, state, pages_total, pages_done,"
            " error FROM documents WHERE id=?", (document_id,)).fetchone()
    return dict(row) if row else None


def documents(paths: Paths, limit: int = 100, offset: int = 0) -> list[dict]:
    db = store.connect_readonly(paths.database)
    if db is None:
        return []
    with db:
        return [dict(row) for row in db.execute(
            "SELECT id, path, title, format, category, state, pages_total FROM documents"
            " ORDER BY title COLLATE NOCASE LIMIT ? OFFSET ?", (limit, offset))]
