import json
import logging
import re
from datetime import datetime
from typing import Any

import psycopg2

from ai_agent.settings import Settings


logger = logging.getLogger(__name__)

_FORBIDDEN_TABLES = {"property", "lead_property"}


def _forbidden_sql(sql: str) -> bool:
    lowered = sql.lower()
    for table in _FORBIDDEN_TABLES:
        if re.search(rf"\b{re.escape(table)}\b", lowered):
            return True
    return False


class PostgresClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _connect(self):
        return psycopg2.connect(
            host=self._settings.db_host,
            port=self._settings.db_port,
            dbname=self._settings.db_name,
            user=self._settings.db_user,
            password=self._settings.db_password,
            connect_timeout=3,
        )

    def _execute(self, cursor, sql: str, params: tuple[Any, ...] = ()):
        if _forbidden_sql(sql):
            raise ValueError("Forbidden table access attempted (properties)")
        cursor.execute(sql, params)

    def check_connection(self) -> bool:
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    self._execute(cursor, "SELECT 1")
                    cursor.fetchone()
            return True
        except Exception as exc:
            logger.warning("DB connection check failed: %s", exc)
            return False

    def ensure_tables(self) -> None:
        ddl = [
            """
            CREATE TABLE IF NOT EXISTS agent_runs (
                id BIGSERIAL PRIMARY KEY,
                business_id TEXT,
                business_name TEXT NOT NULL,
                state TEXT NOT NULL,
                request_json TEXT NOT NULL,
                response_json TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
        ]
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    for sql in ddl:
                        self._execute(cursor, sql)
        except Exception as exc:
            logger.warning("Failed to ensure agent tables: %s", exc)

    def load_context(self, business_name: str, state: str) -> dict[str, Any]:
        return {
            "business_name": business_name,
            "state": state,
            "note": "No property access; context limited to input values.",
        }

    def save_latest_run(
        self,
        business_id: str | None,
        business_name: str,
        state: str,
        request_json: dict[str, Any],
        response_json: dict[str, Any],
        status: str,
        error_message: str | None,
    ) -> datetime | None:
        try:
            logger.info("run save start")
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    if business_id:
                        self._execute(
                            cursor,
                            "DELETE FROM agent_runs WHERE business_id = %s",
                            (business_id,),
                        )
                    else:
                        self._execute(
                            cursor,
                            "DELETE FROM agent_runs WHERE business_name = %s AND state = %s",
                            (business_name, state),
                        )
                    self._execute(
                        cursor,
                        """
                        INSERT INTO agent_runs (
                            business_id,
                            business_name,
                            state,
                            request_json,
                            response_json,
                            status,
                            error_message,
                            created_at,
                            updated_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                        RETURNING created_at
                        """,
                        (
                            business_id,
                            business_name,
                            state,
                            json.dumps(request_json, default=str),
                            json.dumps(response_json, default=str),
                            status,
                            error_message,
                        ),
                    )
                    row = cursor.fetchone()
                    logger.info("run save done")
                    return row[0] if row else None
        except Exception as exc:
            logger.warning("Failed to save run: %s", exc)
            return None
