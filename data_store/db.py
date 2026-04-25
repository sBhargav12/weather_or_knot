from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Iterable, List, Optional, Tuple


class Database:
    """Small SQLite helper with table-specific insert methods."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._columns_cache: Dict[str, set] = {}

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _normalise_value(value: Any) -> Any:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (dict, list, tuple)):
            return json.dumps(value, default=str)
        return value

    def _table_columns(self, table: str) -> set:
        if table in self._columns_cache:
            return self._columns_cache[table]
        rows = self.execute(f"PRAGMA table_info({table})")
        cols = {row["name"] for row in rows}
        self._columns_cache[table] = cols
        return cols

    def _insert(self, table: str, data: Dict[str, Any]) -> int:
        columns = self._table_columns(table)
        payload = {
            key: self._normalise_value(value)
            for key, value in data.items()
            if key in columns and value is not None
        }
        if not payload:
            raise ValueError(f"No insertable fields supplied for {table}")
        names = list(payload)
        placeholders = ", ".join("?" for _ in names)
        sql = f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})"
        return self.execute_write(sql, tuple(payload[name] for name in names))

    def insert_model_run(self, data: Dict[str, Any]) -> int:
        return self._insert("model_runs", data)

    def insert_observation(self, data: Dict[str, Any]) -> int:
        return self._insert("metar_observations", data)

    def insert_kalshi_price(self, data: Dict[str, Any]) -> int:
        return self._insert("kalshi_prices", data)

    def insert_gate_check(self, data: Dict[str, Any]) -> int:
        return self._insert("gate_checks", data)

    def insert_signal(self, data: Dict[str, Any]) -> int:
        return self._insert("signals", data)

    def insert_paper_trade(self, data: Dict[str, Any]) -> int:
        return self._insert("paper_trades", data)

    def insert_teleconnection(self, data: Dict[str, Any]) -> int:
        return self._upsert_by_date("teleconnections", data)

    def insert_dsm_report(self, data: Dict[str, Any]) -> int:
        return self._insert("dsm_reports", data)

    def insert_cli_report(self, data: Dict[str, Any]) -> int:
        return self._insert("cli_reports", data)

    def insert_candidate_signal(self, data: Dict[str, Any]) -> int:
        return self._insert("candidate_signals", data)

    def update_daily_performance(self, date: str, data: Dict[str, Any]) -> int:
        payload = {"date": date, **data}
        return self._upsert_by_date("performance_daily", payload)

    def _upsert_by_date(self, table: str, data: Dict[str, Any]) -> int:
        columns = self._table_columns(table)
        payload = {
            key: self._normalise_value(value)
            for key, value in data.items()
            if key in columns and value is not None
        }
        if "date" not in payload:
            raise ValueError(f"{table} upsert requires a date field")
        names = list(payload)
        placeholders = ", ".join("?" for _ in names)
        updates = ", ".join(f"{name}=excluded.{name}" for name in names if name != "date")
        sql = (
            f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders}) "
            f"ON CONFLICT(date) DO UPDATE SET {updates}"
        )
        return self.execute_write(sql, tuple(payload[name] for name in names))

    def get_latest_observation(self, station: str) -> Optional[dict]:
        rows = self.execute(
            """
            SELECT * FROM metar_observations
            WHERE station = ?
            ORDER BY observation_time DESC, created_at DESC
            LIMIT 1
            """,
            (station,),
        )
        return dict(rows[0]) if rows else None

    def get_wethr_high_today(self, station: str) -> Optional[float]:
        rows = self.execute(
            """
            SELECT wethr_high_f FROM metar_observations
            WHERE station = ? AND wethr_high_f IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (station,),
        )
        return float(rows[0]["wethr_high_f"]) if rows else None

    def get_open_signals(self, city: str) -> List[dict]:
        rows = self.execute(
            "SELECT * FROM signals WHERE city = ? AND status = 'ACTIVE' ORDER BY created_at",
            (city,),
        )
        return [dict(row) for row in rows]

    def get_open_trades(self) -> List[dict]:
        rows = self.execute(
            "SELECT * FROM paper_trades WHERE exit_time IS NULL ORDER BY created_at"
        )
        return [dict(row) for row in rows]

    def get_model_run_latest(self, city: str, model: str) -> Optional[dict]:
        rows = self.execute(
            """
            SELECT * FROM model_runs
            WHERE city = ? AND model = ?
            ORDER BY run_time DESC, created_at DESC
            LIMIT 1
            """,
            (city, model),
        )
        return dict(rows[0]) if rows else None

    def get_price_history(self, ticker: str, hours: int) -> List[dict]:
        rows = self.execute(
            """
            SELECT * FROM kalshi_prices
            WHERE ticker = ? AND created_at >= datetime('now', ?)
            ORDER BY created_at
            """,
            (ticker, f"-{hours} hours"),
        )
        return [dict(row) for row in rows]

    def get_performance_summary(self, days: int) -> dict:
        rows = self.execute(
            """
            SELECT * FROM performance_daily
            WHERE date >= date('now', ?)
            ORDER BY date
            """,
            (f"-{days} days",),
        )
        return {"days": days, "rows": [dict(row) for row in rows]}

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> List[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(sql, params).fetchall()

    def execute_write(self, sql: str, params: Tuple[Any, ...] = ()) -> int:
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return int(cur.lastrowid or cur.rowcount)

    def executemany_write(self, sql: str, rows: Iterable[Tuple[Any, ...]]) -> int:
        with self._connect() as conn:
            cur = conn.executemany(sql, rows)
            conn.commit()
            return int(cur.rowcount)
