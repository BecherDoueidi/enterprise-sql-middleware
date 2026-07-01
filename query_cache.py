"""
Persistent question/answer cache.

Goal: if a user asks the same question twice (now or after a server
restart), the second time should skip the LLM call and the DB query
entirely and just return the saved answer instantly.

Storage: a small SQLite file (query_cache.db) sitting next to this script.
SQLite is used (rather than an in-memory dict) specifically because it
survives process restarts -- nothing is lost when the server reboots.

Scoping: every entry is keyed on (role_name, donor_id, normalized
question) -- NOT on question text alone. This means a donor's cache and
an admin's cache are physically separate rows, and two different donors
never share an entry either. role_name/donor_id are real columns (not
string-concatenated into the question) so they can be inspected,
audited, and enforced without relying on text parsing.

Matching: the question text is normalized (lowercased, extra whitespace
collapsed) and hashed together with role_name/donor_id. Two questions
that differ only in casing or extra spaces ("Show me revenue" vs
"show me   revenue") will hit the same cache entry, but only if asked by
the same role+donor. This is exact-match-after-normalization, not
fuzzy/semantic matching.

IMPORTANT: a cache hit is a shortcut around the LLM + SQL generation,
but it must NEVER be a shortcut around access control. The caller
(app.py) is responsible for re-validating a cached entry's SQL against
the CURRENT role's allowed_tables (access_control.check_table_access)
before returning it, and for calling invalidate() if that check fails --
otherwise a permissions change (or a bug that let one bad entry through)
would keep being replayed forever.
"""

import sqlite3
import hashlib
import json
import os
from datetime import datetime, timezone

CACHE_DB_PATH = os.path.join(os.path.dirname(__file__), "query_cache.db")


def _get_connection():
    conn = sqlite3.connect(CACHE_DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS query_cache (
            cache_key      TEXT PRIMARY KEY,
            role_name      TEXT NOT NULL,
            donor_id       INTEGER,
            original_query TEXT NOT NULL,
            generated_sql  TEXT NOT NULL,
            result_json    TEXT NOT NULL,
            hit_count      INTEGER NOT NULL DEFAULT 0,
            created_at     TEXT NOT NULL,
            last_used_at   TEXT NOT NULL
        )
        """
    )
    # Backfill for DBs created before role_name/donor_id existed, back
    # when the primary key was just a hash of the raw question text.
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(query_cache)")}
    if "role_name" not in existing_cols:
        # Old rows have no reliable role/donor association -- wipe them
        # rather than guessing, since guessing wrong here means leaking
        # data across roles, which is exactly the bug being fixed.
        conn.execute("DROP TABLE query_cache")
        conn.execute(
            """
            CREATE TABLE query_cache (
                cache_key      TEXT PRIMARY KEY,
                role_name      TEXT NOT NULL,
                donor_id       INTEGER,
                original_query TEXT NOT NULL,
                generated_sql  TEXT NOT NULL,
                result_json    TEXT NOT NULL,
                hit_count      INTEGER NOT NULL DEFAULT 0,
                created_at     TEXT NOT NULL,
                last_used_at   TEXT NOT NULL
            )
            """
        )
    return conn


def _normalize(query_text):
    return " ".join(query_text.strip().lower().split())


def _cache_key(query_text, role_name, donor_id):
    raw = f"{role_name}|{donor_id}|{_normalize(query_text)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_cached(query_text, role_name, donor_id):
    """
    Look up whether this question has been asked before BY THIS SAME
    role+donor. Returns a dict with generated_sql / data / hit_count,
    or None if it's a new question (or was only ever asked by someone
    else's role/donor -- that's a deliberate miss, not a bug).
    """
    cache_key = _cache_key(query_text, role_name, donor_id)
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT generated_sql, result_json, hit_count "
            "FROM query_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if row is None:
            return None

        generated_sql, result_json, hit_count = row
        new_hit_count = hit_count + 1
        conn.execute(
            "UPDATE query_cache SET hit_count = ?, last_used_at = ? "
            "WHERE cache_key = ?",
            (new_hit_count, datetime.now(timezone.utc).isoformat(), cache_key),
        )
        conn.commit()

        return {
            "generated_sql": generated_sql,
            "data": json.loads(result_json),
            "hit_count": new_hit_count,
        }
    finally:
        conn.close()


def set_cached(query_text, role_name, donor_id, generated_sql, data):
    """Save a new question -> answer pair so future repeats (by this same role+donor) are instant."""
    cache_key = _cache_key(query_text, role_name, donor_id)
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO query_cache
                (cache_key, role_name, donor_id, original_query, generated_sql,
                 result_json, hit_count, created_at, last_used_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                generated_sql = excluded.generated_sql,
                result_json   = excluded.result_json,
                last_used_at  = excluded.last_used_at
            """,
            (cache_key, role_name, donor_id, query_text, generated_sql,
             json.dumps(data, default=str), now, now),
        )
        conn.commit()
    finally:
        conn.close()


def invalidate(query_text, role_name, donor_id):
    """
    Remove a single stale/invalid entry (e.g. one that just failed a
    re-validation check against current access-control rules) without
    nuking the whole cache. Safe to call even if the entry no longer
    exists.
    """
    cache_key = _cache_key(query_text, role_name, donor_id)
    conn = _get_connection()
    try:
        conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()
    finally:
        conn.close()


def clear_cache(role_name=None):
    """
    Wipe the cache. If role_name is given, only that role's entries are
    cleared (e.g. an admin clearing just the donor-facing cache after a
    schema change), otherwise everything is cleared.
    """
    conn = _get_connection()
    try:
        if role_name is None:
            conn.execute("DELETE FROM query_cache")
        else:
            conn.execute("DELETE FROM query_cache WHERE role_name = ?", (role_name,))
        conn.commit()
    finally:
        conn.close()
