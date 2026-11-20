"""Persistencia SQLite (WAL) para el prototipo. El SQL es portable a PostgreSQL
cambiando placeholders y `INSERT OR IGNORE` (ver README)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

from .domain import Accommodation, Constraints, Profile

SCHEMA = """
CREATE TABLE IF NOT EXISTS accommodations (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, zone TEXT NOT NULL, type TEXT NOT NULL,
    stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
    price_per_night REAL NOT NULL CHECK (price_per_night >= 0),
    amenities TEXT NOT NULL DEFAULT '[]'
);
-- Proyección CQRS de reservas, ahora con user_id y accommodation_id (ADR-020, D3).
CREATE TABLE IF NOT EXISTS reservation_projection (
    reservation_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, accommodation_id INTEGER,
    hotel_name TEXT, check_in TEXT, check_out TEXT, status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_resproj_user ON reservation_projection(user_id);
CREATE TABLE IF NOT EXISTS user_constraints (
    user_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY, vector TEXT NOT NULL, interactions INTEGER NOT NULL,
    source TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    user_id TEXT NOT NULL, feedback_id TEXT NOT NULL, accommodation_id INTEGER NOT NULL,
    kind TEXT NOT NULL, rating INTEGER, signal REAL NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, feedback_id)
);
CREATE TABLE IF NOT EXISTS recommendation_sets (
    user_id TEXT PRIMARY KEY, items TEXT NOT NULL, strategy TEXT NOT NULL,
    reason TEXT NOT NULL, generated_at TEXT NOT NULL, expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_access_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, admin_sub TEXT NOT NULL,
    target_user_id TEXT NOT NULL, action TEXT NOT NULL, at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        with self.read() as c:
            c.executescript(SCHEMA)

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @contextmanager
    def read(self):
        c = self._conn()
        try:
            yield c
        finally:
            c.close()

    @contextmanager
    def tx(self):
        c = self._conn()
        begun = False
        try:
            c.execute("BEGIN IMMEDIATE")
            begun = True
            yield c
            c.execute("COMMIT")
        except BaseException:
            if begun:
                c.execute("ROLLBACK")
            raise
        finally:
            c.close()


class SqlStore:
    def __init__(self, db: Database):
        self.db = db

    # --- catálogo -------------------------------------------------------
    def upsert_accommodations(self, items) -> None:
        with self.db.tx() as c:
            for a in items:
                c.execute(
                    "INSERT INTO accommodations(id,name,zone,type,stars,price_per_night,amenities)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
                    " zone=excluded.zone, type=excluded.type, stars=excluded.stars,"
                    " price_per_night=excluded.price_per_night, amenities=excluded.amenities",
                    (a.id, a.name, a.zone, a.type, a.stars, a.price_per_night,
                     json.dumps(list(a.amenities))))

    def catalog(self) -> list:
        with self.db.read() as c:
            rows = c.execute("SELECT * FROM accommodations ORDER BY id").fetchall()
        return [Accommodation(r["id"], r["name"], r["zone"], r["type"], r["stars"],
                              r["price_per_night"], tuple(json.loads(r["amenities"])))
                for r in rows]

    # --- historial de reservas -----------------------------------------
    def upsert_reservation(self, reservation_id, user_id, accommodation_id, status,
                           hotel_name=None, check_in=None, check_out=None) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO reservation_projection(reservation_id,user_id,accommodation_id,"
                "hotel_name,check_in,check_out,status) VALUES(?,?,?,?,?,?,?)"
                " ON CONFLICT(reservation_id) DO UPDATE SET user_id=excluded.user_id,"
                " accommodation_id=excluded.accommodation_id, hotel_name=excluded.hotel_name,"
                " check_in=excluded.check_in, check_out=excluded.check_out, status=excluded.status",
                (reservation_id, user_id, accommodation_id, hotel_name, check_in, check_out, status))

    def accommodation_ids_for(self, user_id, statuses) -> list:
        marks = ",".join("?" * len(statuses)) or "''"
        with self.db.read() as c:
            rows = c.execute(
                f"SELECT accommodation_id FROM reservation_projection WHERE user_id=?"
                f" AND accommodation_id IS NOT NULL AND lower(status) IN ({marks})"
                f" ORDER BY reservation_id", (user_id, *statuses)).fetchall()
        return [r["accommodation_id"] for r in rows]

    def popularity(self, statuses) -> dict:
        marks = ",".join("?" * len(statuses)) or "''"
        with self.db.read() as c:
            rows = c.execute(
                f"SELECT accommodation_id, COUNT(*) n FROM reservation_projection"
                f" WHERE accommodation_id IS NOT NULL AND lower(status) IN ({marks})"
                f" GROUP BY accommodation_id", tuple(statuses)).fetchall()
        return {r["accommodation_id"]: r["n"] for r in rows}

    def active_user_ids(self) -> list:
        with self.db.read() as c:
            rows = c.execute(
                "SELECT user_id FROM reservation_projection UNION SELECT user_id FROM user_profiles"
                " UNION SELECT user_id FROM user_constraints UNION SELECT user_id FROM feedback"
                " ORDER BY 1").fetchall()
        return [r["user_id"] for r in rows]

    # --- restricciones --------------------------------------------------
    def get_constraints(self, user_id) -> Constraints:
        with self.db.read() as c:
            r = c.execute("SELECT data FROM user_constraints WHERE user_id=?", (user_id,)).fetchone()
        return Constraints.from_dict(json.loads(r["data"])) if r else Constraints()

    def set_constraints(self, user_id, constraints: Constraints, now_iso) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO user_constraints(user_id,data,updated_at) VALUES(?,?,?)"
                      " ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,"
                      " updated_at=excluded.updated_at",
                      (user_id, json.dumps(constraints.to_dict()), now_iso))

    # --- perfil ---------------------------------------------------------
    @staticmethod
    def _write_profile(c, user_id, p: Profile, now_iso) -> None:
        c.execute("INSERT INTO user_profiles(user_id,vector,interactions,source,updated_at)"
                  " VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET vector=excluded.vector,"
                  " interactions=excluded.interactions, source=excluded.source,"
                  " updated_at=excluded.updated_at",
                  (user_id, json.dumps(p.vector), p.interactions, p.source, now_iso))

    @staticmethod
    def _row_to_profile(r):
        return Profile(json.loads(r["vector"]), r["interactions"], r["source"]) if r else None

    def get_profile(self, user_id):
        with self.db.read() as c:
            return self._row_to_profile(
                c.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone())

    def save_profile(self, user_id, p: Profile, now_iso) -> None:
        with self.db.tx() as c:
            self._write_profile(c, user_id, p, now_iso)

    # --- feedback (idempotente, ADR-020 D4) -----------------------------
    def record_feedback(self, user_id, feedback_id, accommodation_id, kind, rating,
                        signal, now_iso, update_fn) -> bool:
        """Inserta el feedback y actualiza el perfil en una sola transacción.
        Devuelve False (sin efectos) si (user_id, feedback_id) ya existía."""
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO feedback(user_id,feedback_id,accommodation_id,kind,"
                "rating,signal,created_at) VALUES(?,?,?,?,?,?,?)",
                (user_id, feedback_id, accommodation_id, kind, rating, signal, now_iso))
            if cur.rowcount == 0:
                return False
            stored = self._row_to_profile(
                c.execute("SELECT * FROM user_profiles WHERE user_id=?", (user_id,)).fetchone())
            self._write_profile(c, user_id, update_fn(stored), now_iso)
            return True

    def latest_signals(self, user_id) -> dict:
        with self.db.read() as c:
            rows = c.execute("SELECT accommodation_id, signal FROM feedback WHERE user_id=?"
                             " ORDER BY created_at, rowid", (user_id,)).fetchall()
        return {r["accommodation_id"]: r["signal"] for r in rows}

    # --- recomendaciones ------------------------------------------------
    def save_set(self, user_id, items, strategy, reason, generated_at, expires_at) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO recommendation_sets(user_id,items,strategy,reason,"
                      "generated_at,expires_at) VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE"
                      " SET items=excluded.items, strategy=excluded.strategy,"
                      " reason=excluded.reason, generated_at=excluded.generated_at,"
                      " expires_at=excluded.expires_at",
                      (user_id, json.dumps(items), strategy, reason, generated_at, expires_at))

    def get_set(self, user_id):
        with self.db.read() as c:
            r = c.execute("SELECT * FROM recommendation_sets WHERE user_id=?", (user_id,)).fetchone()
        if not r:
            return None
        return {"items": json.loads(r["items"]), "strategy": r["strategy"], "reason": r["reason"],
                "generated_at": r["generated_at"], "expires_at": r["expires_at"]}

    # --- auditoría ------------------------------------------------------
    def add_audit(self, admin_sub, target_user_id, action, at_iso) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO profile_access_audit(admin_sub,target_user_id,action,at)"
                      " VALUES(?,?,?,?)", (admin_sub, target_user_id, action, at_iso))

    def list_audit(self, limit=100) -> list:
        with self.db.read() as c:
            rows = c.execute("SELECT admin_sub,target_user_id,action,at FROM profile_access_audit"
                             " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
