from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 기준 경로
BASE_DIR = Path(__file__).resolve().parent # /home/z/z/backend
PROJECT_ROOT = BASE_DIR.parent # /home/z/z

# DB 디렉터리
DB_DIR = PROJECT_ROOT / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)

# 기본 DB 파일 경로
_DEFAULT_TRADES_DB = DB_DIR / "z_trades.db"
_DEFAULT_STATE_DB = DB_DIR / "z_state.db"

# 실제 사용 경로 (환경변수로 오버라이드 가능)
DB_PATH: str = os.environ.get("Z_TRADES_DB", str(_DEFAULT_TRADES_DB))
STATE_DB_PATH: str = os.environ.get("Z_STATE_DB", str(_DEFAULT_STATE_DB))

# SQLAlchemy용 URL ← 이게 없어서 방금까지 계속 터진 것
SQLALCHEMY_DATABASE_URL: str = os.environ.get(
    "Z_SQLALCHEMY_DATABASE_URL",
    f"sqlite:///{DB_PATH}",
)

# 지표 기본 설정
DEFAULT_EQUITY_WINDOW_DAYS: int = int(
    os.environ.get("Z_DEFAULT_EQUITY_WINDOW_DAYS", "90")
)
MAX_EQUITY_WINDOW_DAYS: int = int(
    os.environ.get("Z_MAX_EQUITY_WINDOW_DAYS", "365")
)

# SQL 로그/디버그 플래그
DEBUG_SQL: bool = os.environ.get("Z_DEBUG_SQL", "0") == "1"