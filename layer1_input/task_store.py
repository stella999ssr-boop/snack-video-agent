"""素材生成任务状态的 SQLite 持久化。"""

import json
import os
import sqlite3
import threading
import time

from layer6_execution.state import AgentState


class TaskStateStore:
    """使用独立数据表保存 AgentState，支持 Railway 重启后查询。"""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=15)

    def _initialize(self):
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS creative_task_states (
                    request_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def save(self, state: AgentState):
        payload = json.dumps(
            state.to_persisted_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        for attempt in range(3):
            try:
                with self._lock, self._connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO creative_task_states(request_id, state_json, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(request_id) DO UPDATE SET
                            state_json = excluded.state_json,
                            updated_at = excluded.updated_at
                        """,
                        (state.session_id, payload, state.updated_at),
                    )
                return
            except sqlite3.OperationalError:
                if attempt == 2:
                    raise
                time.sleep(0.1 * (attempt + 1))

    def get(self, request_id: str) -> AgentState | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_json
                FROM creative_task_states
                WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return AgentState.from_persisted_dict(json.loads(row[0]))

    def list_all(self) -> list[AgentState]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT state_json
                FROM creative_task_states
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [
            AgentState.from_persisted_dict(json.loads(row[0]))
            for row in rows
        ]

    def delete(self, request_id: str) -> bool:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM creative_task_states WHERE request_id = ?",
                (request_id,),
            )
        return cursor.rowcount > 0
