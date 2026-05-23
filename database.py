import aiosqlite
import os
from datetime import datetime
from typing import Optional

DB_PATH = os.getenv("DB_PATH", "/data/workout.db")


class Database:
    def __init__(self):
        self.path = DB_PATH

    async def init(self):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS workouts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    day_num     INTEGER NOT NULL,
                    started_at  TEXT NOT NULL,
                    finished_at TEXT,
                    completed   INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS exercise_logs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    workout_id    INTEGER NOT NULL,
                    exercise_id   TEXT NOT NULL,
                    exercise_name TEXT NOT NULL,
                    set_num       INTEGER NOT NULL,
                    reps_target   TEXT,
                    weight        REAL,
                    logged_at     TEXT NOT NULL,
                    FOREIGN KEY (workout_id) REFERENCES workouts(id)
                )
            """)
            await db.commit()

    async def create_workout(self, user_id: int, day_num: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO workouts (user_id, day_num, started_at) VALUES (?, ?, ?)",
                (user_id, day_num, datetime.now().isoformat()),
            )
            await db.commit()
            return cur.lastrowid

    async def log_set(
        self,
        workout_id: int,
        exercise_id: str,
        exercise_name: str,
        set_num: int,
        reps_target: str,
        weight: Optional[float],
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO exercise_logs
                   (workout_id, exercise_id, exercise_name, set_num, reps_target, weight, logged_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (workout_id, exercise_id, exercise_name, set_num, reps_target, weight, datetime.now().isoformat()),
            )
            await db.commit()

    async def complete_workout(self, workout_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE workouts SET completed=1, finished_at=? WHERE id=?",
                (datetime.now().isoformat(), workout_id),
            )
            await db.commit()

    async def get_history(self, user_id: int, limit: int = 7):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM workouts WHERE user_id=? ORDER BY started_at DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_last_day(self, user_id: int) -> Optional[int]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT day_num FROM workouts WHERE user_id=? AND completed=1 ORDER BY started_at DESC LIMIT 1",
                (user_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else None

    async def get_exercise_progress(self, user_id: int, exercise_id: str, limit: int = 10):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """SELECT w.started_at AS date, MAX(el.weight) AS max_weight
                   FROM exercise_logs el
                   JOIN workouts w ON el.workout_id = w.id
                   WHERE w.user_id=? AND el.exercise_id=? AND el.weight IS NOT NULL
                   GROUP BY w.id
                   ORDER BY w.started_at DESC LIMIT ?""",
                (user_id, exercise_id, limit),
            )
            rows = await cur.fetchall()
            return [{"date": r[0], "max_weight": r[1]} for r in rows]

    async def get_total_sets(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """SELECT COUNT(*) FROM exercise_logs el
                   JOIN workouts w ON el.workout_id = w.id
                   WHERE w.user_id=?""",
                (user_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_workout_count(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM workouts WHERE user_id=? AND completed=1",
                (user_id,),
            )
            row = await cur.fetchone()
            return row[0] if row else 0
