import sqlite3
import json
from pathlib import Path
from typing import Optional
from .models import Listing


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    uid TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    price_eur INTEGER,
    sqm REAL,
    rooms REAL,
    location TEXT,
    plz TEXT,
    description TEXT,
    image_url TEXT,
    content_hash TEXT,
    raw_json TEXT,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    llm_score INTEGER,
    llm_reasoning TEXT,
    llm_red_flags TEXT,
    llm_evaluated_at TEXT,
    notified_at TEXT,
    dismissed INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_notified ON listings(notified_at);
CREATE INDEX IF NOT EXISTS idx_score ON listings(llm_score);
"""


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert(self, listing: Listing) -> bool:
        """Insert listing if new. Returns True if newly inserted."""
        cur = self.conn.execute("SELECT uid FROM listings WHERE uid = ?", (listing.uid,))
        exists = cur.fetchone() is not None
        if exists:
            self.conn.execute(
                "UPDATE listings SET last_seen = CURRENT_TIMESTAMP WHERE uid = ?",
                (listing.uid,),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """INSERT INTO listings
            (uid, source, source_id, url, title, price_eur, sqm, rooms, location, plz,
             description, image_url, content_hash, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                listing.uid,
                listing.source,
                listing.source_id,
                listing.url,
                listing.title,
                listing.price_eur,
                listing.sqm,
                listing.rooms,
                listing.location,
                listing.plz,
                listing.description,
                listing.image_url,
                listing.content_hash(),
                json.dumps(listing.raw, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return True

    def unevaluated(self, limit: int = 50) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM listings WHERE llm_score IS NULL AND dismissed = 0 ORDER BY first_seen DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def save_evaluation(self, uid: str, score: int, reasoning: str, red_flags: str):
        self.conn.execute(
            """UPDATE listings SET llm_score = ?, llm_reasoning = ?, llm_red_flags = ?,
               llm_evaluated_at = CURRENT_TIMESTAMP WHERE uid = ?""",
            (score, reasoning, red_flags, uid),
        )
        self.conn.commit()

    def pending_notification(self, min_score: int) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """SELECT * FROM listings
               WHERE llm_score >= ? AND notified_at IS NULL AND dismissed = 0
               ORDER BY llm_score DESC, first_seen DESC""",
            (min_score,),
        )
        return cur.fetchall()

    def mark_notified(self, uid: str):
        self.conn.execute(
            "UPDATE listings SET notified_at = CURRENT_TIMESTAMP WHERE uid = ?", (uid,)
        )
        self.conn.commit()

    def stats(self) -> dict:
        cur = self.conn.execute(
            """SELECT source, COUNT(*) as n,
               SUM(CASE WHEN llm_score IS NOT NULL THEN 1 ELSE 0 END) as evaluated,
               SUM(CASE WHEN notified_at IS NOT NULL THEN 1 ELSE 0 END) as notified
               FROM listings GROUP BY source"""
        )
        return {r["source"]: dict(r) for r in cur.fetchall()}

    def close(self):
        self.conn.close()
