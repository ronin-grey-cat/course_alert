import sqlite3
import os
import threading
from contextlib import contextmanager

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./course_alert.db")
_lock = threading.Lock()


def _get_conn():
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db(write=False):
    conn = _get_conn()
    try:
        if write:
            with _lock:
                yield conn
                conn.commit()
        else:
            yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with _db(write=True) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS watched_courses (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tgs_ref      TEXT NOT NULL UNIQUE,
                title        TEXT NOT NULL,
                provider     TEXT NOT NULL DEFAULT '',
                course_url   TEXT NOT NULL DEFAULT '',
                added_at     TEXT NOT NULL DEFAULT (datetime('now')),
                last_checked TEXT,
                last_status  TEXT CHECK(last_status IN ('no_runs','has_runs','error'))
                             DEFAULT 'no_runs'
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint   TEXT NOT NULL UNIQUE,
                p256dh     TEXT NOT NULL,
                auth       TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS subscription_courses (
                subscription_id INTEGER NOT NULL
                    REFERENCES push_subscriptions(id) ON DELETE CASCADE,
                tgs_ref         TEXT NOT NULL
                    REFERENCES watched_courses(tgs_ref) ON DELETE CASCADE,
                PRIMARY KEY (subscription_id, tgs_ref)
            );

            CREATE INDEX IF NOT EXISTS idx_sub_courses_tgs
                ON subscription_courses(tgs_ref);
        """)


# ── Watched courses ──────────────────────────────────────────────────────────

def upsert_watched_course(tgs_ref, title, provider, course_url):
    with _db(write=True) as conn:
        conn.execute("""
            INSERT INTO watched_courses (tgs_ref, title, provider, course_url)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tgs_ref) DO NOTHING
        """, (tgs_ref, title, provider, course_url))


def remove_watched_course_for_sub(tgs_ref, endpoint):
    with _db(write=True) as conn:
        row = conn.execute(
            "SELECT id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        ).fetchone()
        if not row:
            return
        conn.execute(
            "DELETE FROM subscription_courses WHERE subscription_id = ? AND tgs_ref = ?",
            (row["id"], tgs_ref)
        )
        still_watched = conn.execute(
            "SELECT 1 FROM subscription_courses WHERE tgs_ref = ?", (tgs_ref,)
        ).fetchone()
        if not still_watched:
            conn.execute("DELETE FROM watched_courses WHERE tgs_ref = ?", (tgs_ref,))


def get_all_watched_courses():
    with _db() as conn:
        rows = conn.execute(
            "SELECT tgs_ref, title, provider, course_url, added_at, "
            "last_checked, last_status FROM watched_courses"
        ).fetchall()
        return [dict(r) for r in rows]


def update_course_status(tgs_ref, status):
    with _db(write=True) as conn:
        conn.execute("""
            UPDATE watched_courses
            SET last_status = ?, last_checked = datetime('now')
            WHERE tgs_ref = ?
        """, (status, tgs_ref))


# ── Push subscriptions ────────────────────────────────────────────────────────

def upsert_subscription(endpoint, p256dh, auth):
    with _db(write=True) as conn:
        conn.execute("""
            INSERT INTO push_subscriptions (endpoint, p256dh, auth)
            VALUES (?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh,
                                                auth    = excluded.auth
        """, (endpoint, p256dh, auth))


def link_subscription_to_course(endpoint, tgs_ref):
    with _db(write=True) as conn:
        row = conn.execute(
            "SELECT id FROM push_subscriptions WHERE endpoint = ?", (endpoint,)
        ).fetchone()
        if not row:
            return
        conn.execute("""
            INSERT OR IGNORE INTO subscription_courses (subscription_id, tgs_ref)
            VALUES (?, ?)
        """, (row["id"], tgs_ref))


def get_subscribers_for_course(tgs_ref):
    with _db() as conn:
        rows = conn.execute("""
            SELECT ps.endpoint, ps.p256dh, ps.auth
            FROM push_subscriptions ps
            JOIN subscription_courses sc ON sc.subscription_id = ps.id
            WHERE sc.tgs_ref = ?
        """, (tgs_ref,)).fetchall()
        return [dict(r) for r in rows]


def delete_subscription(endpoint):
    with _db(write=True) as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def force_remove_watched_course(tgs_ref):
    with _db(write=True) as conn:
        conn.execute("DELETE FROM watched_courses WHERE tgs_ref = ?", (tgs_ref,))


def get_watched_courses_for_sub(endpoint):
    with _db() as conn:
        rows = conn.execute("""
            SELECT wc.tgs_ref, wc.title, wc.provider, wc.course_url,
                   wc.added_at, wc.last_checked, wc.last_status
            FROM watched_courses wc
            JOIN subscription_courses sc ON sc.tgs_ref = wc.tgs_ref
            JOIN push_subscriptions ps ON ps.id = sc.subscription_id
            WHERE ps.endpoint = ?
        """, (endpoint,)).fetchall()
        return [dict(r) for r in rows]
