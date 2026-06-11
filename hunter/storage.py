import sqlite3
import json
from pathlib import Path
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
    llm_in_corridor INTEGER,
    llm_evaluated_at TEXT,
    notified_at TEXT,
    dismissed INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_notified ON listings(notified_at);
CREATE INDEX IF NOT EXISTS idx_score ON listings(llm_score);
"""

# Columns added after the initial schema; applied to pre-existing DBs.
MIGRATIONS = [
    "ALTER TABLE listings ADD COLUMN llm_in_corridor INTEGER",
]


class Storage:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        for stmt in MIGRATIONS:
            try:
                self.conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        self.conn.commit()

    def upsert(self, listing: Listing) -> str:
        """Insert or refresh a listing. Returns "new", "changed", or "seen".

        "changed" means the content hash (title/price/sqm/location) differs
        from the stored row — e.g. a price drop. The row is updated and its
        evaluation/notification state reset so it gets re-scored and,
        if it still clears the threshold, re-pushed.
        """
        cur = self.conn.execute(
            "SELECT content_hash FROM listings WHERE uid = ?", (listing.uid,)
        )
        row = cur.fetchone()
        new_hash = listing.content_hash()
        if row is not None:
            if row["content_hash"] == new_hash:
                self.conn.execute(
                    "UPDATE listings SET last_seen = CURRENT_TIMESTAMP WHERE uid = ?",
                    (listing.uid,),
                )
                self.conn.commit()
                return "seen"
            self.conn.execute(
                """UPDATE listings SET
                   title = ?, price_eur = ?, sqm = ?, rooms = ?, location = ?, plz = ?,
                   description = ?, image_url = ?, content_hash = ?, raw_json = ?,
                   last_seen = CURRENT_TIMESTAMP,
                   llm_score = NULL, llm_reasoning = NULL, llm_red_flags = NULL,
                   llm_in_corridor = NULL, llm_evaluated_at = NULL, notified_at = NULL
                   WHERE uid = ?""",
                (
                    listing.title,
                    listing.price_eur,
                    listing.sqm,
                    listing.rooms,
                    listing.location,
                    listing.plz,
                    listing.description,
                    listing.image_url,
                    new_hash,
                    json.dumps(listing.raw, ensure_ascii=False),
                    listing.uid,
                ),
            )
            self.conn.commit()
            return "changed"
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
                new_hash,
                json.dumps(listing.raw, ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return "new"

    def unevaluated(self, limit: int = 50) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            "SELECT * FROM listings WHERE llm_score IS NULL AND dismissed = 0 ORDER BY first_seen DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()

    def update_description(self, uid: str, description: str):
        """Enrich a listing with detail text fetched after the list scrape."""
        self.conn.execute(
            "UPDATE listings SET description = ? WHERE uid = ?", (description, uid)
        )
        self.conn.commit()

    def save_evaluation(
        self, uid: str, score: int, reasoning: str, red_flags: str, in_corridor: bool
    ):
        self.conn.execute(
            """UPDATE listings SET llm_score = ?, llm_reasoning = ?, llm_red_flags = ?,
               llm_in_corridor = ?, llm_evaluated_at = CURRENT_TIMESTAMP WHERE uid = ?""",
            (score, reasoning, red_flags, int(in_corridor), uid),
        )
        self.conn.commit()

    def pending_notification(self, min_score: int) -> list[sqlite3.Row]:
        # The NOT EXISTS clause skips cross-source duplicates: same house
        # (identical title/price/sqm/location hash) already pushed under
        # another uid.
        cur = self.conn.execute(
            """SELECT * FROM listings l
               WHERE llm_score >= ? AND notified_at IS NULL AND dismissed = 0
               AND NOT EXISTS (
                   SELECT 1 FROM listings o
                   WHERE o.content_hash = l.content_hash
                     AND o.uid != l.uid AND o.notified_at IS NOT NULL
               )
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
