import sqlite3, json, time
from collections import OrderedDict
import numpy as np
from config import DB_PATH


class LRU:
    def __init__(self, cap=128):
        self.cap, self.d = cap, OrderedDict()

    def get(self, k):
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        return None

    def put(self, k, v):
        self.d[k] = v
        self.d.move_to_end(k)
        if len(self.d) > self.cap:
            self.d.popitem(last=False)


class Store:
    """Tier 2 (facts / user model) + Tier 3 (episodes / semantic) + hot cache.
    Every row is partitioned by user_id — the seam that shards to millions of users."""

    def __init__(self, path=DB_PATH):
        self.db = sqlite3.connect(path)
        self.cache = LRU()
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS facts(
          id INTEGER PRIMARY KEY, user_id TEXT, key TEXT, value TEXT,
          valid_at REAL, invalid_at REAL, status TEXT);   -- tier 2, temporal
        CREATE TABLE IF NOT EXISTS episodes(
          id INTEGER PRIMARY KEY, user_id TEXT, text TEXT, vec TEXT,
          at REAL, importance REAL);                       -- tier 3, semantic
        CREATE INDEX IF NOT EXISTS ix_facts_user    ON facts(user_id);
        CREATE INDEX IF NOT EXISTS ix_episodes_user ON episodes(user_id);
        """)
        self.db.commit()

    # ---- Tier 2: user memory with temporal validity ----
    def upsert_fact(self, user_id, key, value):
        now = time.time()
        # supersede any current fact with the same key (contradiction handling)
        self.db.execute("""UPDATE facts SET invalid_at=?, status='superseded'
                           WHERE user_id=? AND key=? AND invalid_at IS NULL""",
                        (now, user_id, key))
        self.db.execute("""INSERT INTO facts(user_id,key,value,valid_at,invalid_at,status)
                           VALUES(?,?,?,?,NULL,'canonical')""",
                        (user_id, key, value, now))
        self.db.commit()
        self.cache.put(("facts", user_id), None)   # invalidate

    def current_facts(self, user_id):
        cached = self.cache.get(("facts", user_id))
        if cached is not None:
            return cached
        rows = self.db.execute("""SELECT key,value FROM facts
                                  WHERE user_id=? AND invalid_at IS NULL
                                  ORDER BY valid_at""", (user_id,)).fetchall()
        self.cache.put(("facts", user_id), rows)
        return rows

    # ---- Tier 3: episodic / semantic recall ----
    def add_episode(self, user_id, text, vec, importance=1.0):
        self.db.execute("""INSERT INTO episodes(user_id,text,vec,at,importance)
                           VALUES(?,?,?,?,?)""",
                        (user_id, text, json.dumps(vec), time.time(), importance))
        self.db.commit()

    def search(self, user_id, qvec, k, now=None):
        """Scoped retrieval: top-k by importance × recency-decay × cosine — for THIS user only."""
        now = now or time.time()
        q = np.array(qvec, dtype=np.float32)
        out = []
        for text, vec, at, imp in self.db.execute(
                "SELECT text,vec,at,importance FROM episodes WHERE user_id=?", (user_id,)):
            v = np.array(json.loads(vec), dtype=np.float32)
            cos = float(q @ v)                              # vectors are unit-norm
            decay = 0.5 ** ((now - at) / (7 * 86400))       # half-life ~1 week
            out.append((imp * (0.6 * cos + 0.4 * decay), text))
        out.sort(reverse=True)
        return [t for _, t in out[:k]]

    def forget_user(self, user_id):
        """GDPR right-to-be-forgotten: delete tiers 2+3 for a user, then you'd re-index."""
        self.db.execute("DELETE FROM facts    WHERE user_id=?", (user_id,))
        self.db.execute("DELETE FROM episodes WHERE user_id=?", (user_id,))
        self.db.commit()
        self.cache.put(("facts", user_id), None)   # invalidate stale cached facts
