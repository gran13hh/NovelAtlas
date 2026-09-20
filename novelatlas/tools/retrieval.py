"""Disposable Chinese bigram FTS5 retrieval with exact source verification."""

import re
import sqlite3
from hashlib import sha256

from novelatlas.schemas.knowledge import Evidence, Passage, SearchArgs
from novelatlas.schemas.parsing import ParsedDocument
from novelatlas.services.temporary_storage import TemporaryUploadStorage


def grams(text: str) -> list[str]:
    parts = re.findall(r"[\u3400-\u9fff]+|[a-zA-Z0-9_]+", text.lower())
    result = []
    for part in parts:
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            result.extend(part[i : i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                result.append(part)
        else:
            result.append(part)
    return list(dict.fromkeys(result))


class SourceIndex:
    def __init__(self, storage: TemporaryUploadStorage, task_id: str):
        self.storage, self.task_id = storage, task_id
        self.path = storage.source_path(task_id).parent / "retrieval.sqlite"

    def ensure(self) -> str:
        source = self.storage.source_path(self.task_id).read_text(encoding="utf-8")
        parsed_json = self.storage.read_json_artifact(self.task_id, "parse-result")
        fingerprint = sha256((source + parsed_json).encode()).hexdigest()
        parsed = ParsedDocument.model_validate_json(parsed_json)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS meta (fingerprint TEXT)")
            row = db.execute("SELECT fingerprint FROM meta").fetchone()
            if row and row[0] == fingerprint:
                return fingerprint
            db.execute("DROP TABLE IF EXISTS passages")
            db.execute("DROP TABLE IF EXISTS lexical")
            db.execute("CREATE TABLE passages (id TEXT PRIMARY KEY, payload TEXT)")
            db.execute("CREATE VIRTUAL TABLE lexical USING fts5(id UNINDEXED, terms)")
            for chunk in parsed.chunks:
                text = (
                    chunk.content_override
                    if chunk.content_override is not None
                    else source[chunk.reference.start_char : chunk.reference.end_char]
                )
                for offset in range(0, len(text), 1000):
                    content = text[offset : offset + 1200]
                    pid = (
                        "passage_"
                        + sha256(
                            f"{chunk.chunk_id}:{offset}:{content}".encode()
                        ).hexdigest()[:24]
                    )
                    edited = chunk.content_override is not None
                    passage = Passage(
                        passage_id=pid,
                        chapter_id=chunk.chapter_id,
                        chunk_id=chunk.chunk_id,
                        start_char=offset
                        if edited
                        else chunk.reference.start_char + offset,
                        end_char=offset + len(content)
                        if edited
                        else chunk.reference.start_char + offset + len(content),
                        content=content,
                        origin="user_edit" if edited else "original",
                    )
                    db.execute(
                        "INSERT INTO passages VALUES (?,?)",
                        (pid, passage.model_dump_json()),
                    )
                    db.execute(
                        "INSERT INTO lexical VALUES (?,?)",
                        (pid, " ".join(grams(content))),
                    )
            db.execute("DELETE FROM meta")
            db.execute("INSERT INTO meta VALUES (?)", (fingerprint,))
        return fingerprint

    def search(self, args: SearchArgs) -> list[Passage]:
        self.storage.get(self.task_id)
        terms = grams(args.query)[:100]
        if not terms:
            return []
        match = " OR ".join('"' + t + '"' for t in terms)
        query = "SELECT p.payload, bm25(lexical) FROM lexical JOIN passages p ON p.id=lexical.id WHERE lexical MATCH ?"
        parameters = [match]
        if args.chapter_ids:
            placeholders = ",".join("?" for _ in args.chapter_ids)
            query += f" AND json_extract(p.payload, '$.chapter_id') IN ({placeholders})"
            parameters.extend(args.chapter_ids)
        query += " ORDER BY bm25(lexical) LIMIT 200"
        with sqlite3.connect(self.path) as db:
            rows = db.execute(query, parameters).fetchall()
        results = []
        seen = set()
        for payload, rank in rows:
            p = Passage.model_validate_json(payload)
            if args.chapter_ids and p.chapter_id not in args.chapter_ids:
                continue
            key = (p.chapter_id, p.content)
            if key in seen:
                continue
            seen.add(key)
            p.score = -rank
            results.append(p)
            if len(results) >= args.limit:
                break
        return results

    def verify(self, evidence: Evidence) -> bool:
        self.storage.get(self.task_id)
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT payload FROM passages WHERE id=?", (evidence.passage_id,)
            ).fetchone()
        if row is None:
            return False
        p = Passage.model_validate_json(row[0])
        return (
            p.chapter_id == evidence.chapter_id
            and p.chunk_id == evidence.chunk_id
            and evidence.origin == p.origin
            and evidence.quote in p.content
        )

    def first(self) -> Passage | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute(
                "SELECT payload FROM passages ORDER BY rowid LIMIT 1"
            ).fetchone()
        return Passage.model_validate_json(row[0]) if row else None
