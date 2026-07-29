from __future__ import annotations

"""
z_state_db.py

Z-OS 런타임 상태 및 부가 데이터를 SQLite 파일에 저장/조회하는 모듈.

1) 공용 SQLite 커넥션 헬퍼
   - STATE_DB_PATH 경로의 SQLite 파일 사용
   - app_state / equity_cache 테이블 스키마 초기화
   - get_state_conn(), rows_to_dict() 제공

2) 상태 스냅샷용 ZStateDB
   - 테이블: state_snapshots
        id INTEGER PRIMARY KEY AUTOINCREMENT
        created_at TEXT (UTC ISO8601)
        label TEXT (예: "live", "shadow", "dummy" 등)
        version TEXT (임의 버전 문자열, git SHA 등)
        payload TEXT (state 전체를 JSON dump)
        meta TEXT (옵션, 추가 메타데이터 JSON)
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List

# --------------------------------------------------------------------- #
# 공용 DB 설정
# --------------------------------------------------------------------- #

STATE_DB_PATH = "/home/z/z/backend/z_state.db"

__all__ = [
    "STATE_DB_PATH",
    "StateSnapshot",
    "ZStateDBError",
    "ZStateDB",
    "get_state_conn",
    "rows_to_dict",
]


def _ensure_db() -> None:
    """
    STATE_DB_PATH 에 기본 테이블(app_state, equity_cache) 생성.

    - app_state: key/value 설정 저장
    - equity_cache: equity/balance/DD 캐시
    """
    path = Path(STATE_DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS equity_cache (
                ts TEXT PRIMARY KEY,
                equity REAL NOT NULL,
                balance REAL NOT NULL,
                dd_pct REAL NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def get_state_conn() -> sqlite3.Connection:
    """
    공용 STATE_DB_PATH SQLite 커넥션 반환.

    - row_factory 를 sqlite3.Row 로 세팅
    """
    _ensure_db()
    conn = sqlite3.connect(STATE_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def rows_to_dicts(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    """
    sqlite3.Cursor → dict 리스트 헬퍼.
    """
    rows = cursor.fetchall()
    if not rows:
        return []
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


# --------------------------------------------------------------------- #
# 상태 스냅샷용 ZStateDB
# --------------------------------------------------------------------- #


@dataclass(frozen=True)
class StateSnapshot:
    id: int
    created_at: datetime
    label: str
    version: Optional[str]
    payload: Dict[str, Any]
    meta: Dict[str, Any]


class ZStateDBError(RuntimeError):
    """state_snapshots 레이어에서 발생하는 모든 에러의 래퍼."""


class ZStateDB:
    """
    상태 스냅샷을 SQLite 파일에 저장/조회하는 유틸.

    사용 예:
        db = ZStateDB(STATE_DB_PATH)
        snap = db.save_snapshot({"equity": 1234.5}, label="live")
        latest = db.load_latest(label="live")
    """

    def __init__(self, db_path: str | Path = STATE_DB_PATH) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._ensure_schema()

    # ------------------------------------------------------------------ #
    # 내부 유틸
    # ------------------------------------------------------------------ #

    def _connect(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(
                self._db_path,
                isolation_level=None, # autocommit
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            return conn
        except Exception as e: # pragma: no cover
            raise ZStateDBError(f"failed to open DB: {self._db_path!s}") from e

    def _ensure_schema(self) -> None:
        """
        state_snapshots 테이블/인덱스 생성.
        """
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS state_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        created_at TEXT NOT NULL,
                        label TEXT NOT NULL,
                        version TEXT,
                        payload TEXT NOT NULL,
                        meta TEXT
                    );
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_state_snapshots_label_created
                        ON state_snapshots(label, created_at DESC);
                    """
                )
            except Exception as e:
                raise ZStateDBError("failed to ensure schema") from e
            finally:
                conn.close()

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    @property
    def path(self) -> Path:
        return self._db_path

    def save_snapshot(
        self,
        state: Dict[str, Any],
        *,
        label: str = "live",
        version: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
    ) -> StateSnapshot:
        """
        현재 상태 dict 를 DB에 스냅샷으로 저장하고, 저장된 기록을 반환.
        """
        created_at = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
        meta_json = json.dumps(meta or {}, separators=(",", ":"), ensure_ascii=False)

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    INSERT INTO state_snapshots (created_at, label, version, payload, meta)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (created_at, label, version, payload_json, meta_json),
                )
                snapshot_id = cur.lastrowid
            except Exception as e:
                raise ZStateDBError("failed to save snapshot") from e
            finally:
                conn.close()

        return StateSnapshot(
            id=int(snapshot_id),
            created_at=datetime.fromisoformat(created_at),
            label=label,
            version=version,
            payload=state,
            meta=meta or {},
        )

    def load_latest(self, *, label: Optional[str] = None) -> Optional[StateSnapshot]:
        """
        가장 최근 스냅샷을 로드.
        label 이 주어지면 해당 label 에서만 검색.
        없으면 None 반환.
        """
        query = """
            SELECT id, created_at, label, version, payload, meta
            FROM state_snapshots
        """
        params: list[Any] = []
        if label:
            query += " WHERE label = ?"
            params.append(label)
        query += " ORDER BY datetime(created_at) DESC LIMIT 1"

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(query, params)
                row = cur.fetchone()
            except Exception as e:
                raise ZStateDBError("failed to load latest snapshot") from e
            finally:
                conn.close()

        if not row:
            return None

        return self._row_to_snapshot(row)

    def load_by_id(self, snapshot_id: int) -> Optional[StateSnapshot]:
        """
        id 로 특정 스냅샷 로드. 없으면 None.
        """
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(
                    """
                    SELECT id, created_at, label, version, payload, meta
                    FROM state_snapshots
                    WHERE id = ?
                    """,
                    (snapshot_id,),
                )
                row = cur.fetchone()
            except Exception as e:
                raise ZStateDBError("failed to load snapshot by id") from e
            finally:
                conn.close()

        if not row:
            return None

        return self._row_to_snapshot(row)

    def list_snapshots(
        self,
        *,
        label: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[StateSnapshot]:
        """
        스냅샷 목록을 최신순으로 조회.
        """
        query = """
            SELECT id, created_at, label, version, payload, meta
            FROM state_snapshots
        """
        params: list[Any] = []
        if label:
            query += " WHERE label = ?"
            params.append(label)
        query += " ORDER BY datetime(created_at) DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute(query, params)
                rows = cur.fetchall()
            except Exception as e:
                raise ZStateDBError("failed to list snapshots") from e
            finally:
                conn.close()

        return [self._row_to_snapshot(r) for r in rows]

    def prune(self, *, keep_last: int = 1000, label: Optional[str] = None) -> int:
        """
        오래된 스냅샷을 삭제.

        keep_last 개수만 남기고 나머지 삭제.
        label 이 주어지면 해당 label 에 대해서만 적용.
        삭제된 row 수를 반환.
        """
        if keep_last <= 0:
            return 0

        with self._lock:
            conn = self._connect()
            try:
                base_query = """
                    SELECT id FROM state_snapshots
                """
                params: list[Any] = []
                if label:
                    base_query += " WHERE label = ?"
                    params.append(label)
                base_query += " ORDER BY datetime(created_at) DESC LIMIT -1 OFFSET ?"

                cur = conn.execute(base_query, [*params, keep_last])
                ids = [row[0] for row in cur.fetchall()]
                if not ids:
                    return 0

                q_marks = ",".join("?" for _ in ids)
                del_cur = conn.execute(
                    f"DELETE FROM state_snapshots WHERE id IN ({q_marks})",
                    ids,
                )
                deleted = del_cur.rowcount or 0
            except Exception as e:
                raise ZStateDBError("failed to prune snapshots") from e
            finally:
                conn.close()

        return int(deleted)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row | tuple[Any, ...]) -> StateSnapshot:
        (
            snapshot_id,
            created_at,
            label,
            version,
            payload_json,
            meta_json,
        ) = row

        if isinstance(created_at, str):
            created_dt = datetime.fromisoformat(created_at)
        elif isinstance(created_at, datetime):
            created_dt = created_at.replace(tzinfo=timezone.utc)
        else:
            created_dt = datetime.now(timezone.utc)

        payload = json.loads(payload_json or "{}")
        meta = json.loads(meta_json or "{}")
        return StateSnapshot(
            id=int(snapshot_id),
            created_at=created_dt,
            label=str(label),
            version=str(version) if version is not None else None,
            payload=payload,
            meta=meta,
        )
