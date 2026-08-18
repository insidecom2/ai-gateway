from __future__ import annotations

import base64
import math
import os
from collections.abc import Mapping
from datetime import datetime
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

import httpx
import libsql_client
from dotenv import load_dotenv

load_dotenv()


class TursoConfigurationError(ValueError):
    """Raised when the Turso adapter is missing required configuration."""


class TursoAdapter:
    """Small async adapter around the official libSQL Python client."""

    def __init__(
        self,
        database_url: str,
        auth_token: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._database_url = database_url.strip()
        self._auth_token = auth_token
        self._client: libsql_client.Client | None = None
        self._http_client = http_client
        self._owns_http_client = False

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> "TursoAdapter":
        values = os.environ if environ is None else environ
        return cls(
            database_url=values.get("TURSO_DATABASE_URL", ""),
            auth_token=values.get("TURSO_AUTH_TOKEN", ""),
            http_client=http_client,
        )

    @property
    def connected(self) -> bool:
        if self._client is not None:
            return not self._client.closed
        return self._http_client is not None and not self._http_client.is_closed

    async def connect(self) -> "TursoAdapter":
        if not self._database_url:
            raise TursoConfigurationError("TURSO_DATABASE_URL must be set")
        if self._requires_auth and not self._auth_token:
            raise TursoConfigurationError(
                "TURSO_AUTH_TOKEN must be set for remote Turso databases"
            )
        if self.connected:
            if not self._is_local and self._http_client is not None:
                self._http_client.headers["Authorization"] = f"Bearer {self._auth_token}"
            return self

        if self._is_local:
            self._client = libsql_client.create_client(
                self._database_url,
                auth_token=self._auth_token or None,
            )
        else:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient()
                self._owns_http_client = True
            self._http_client.headers["Authorization"] = f"Bearer {self._auth_token}"
        return self

    async def execute(
        self,
        statement: libsql_client.InStatement,
        args: libsql_client.InArgs = None,
    ) -> libsql_client.ResultSet:
        if self._is_local:
            return await self._require_client().execute(statement, args)
        return await self._execute_remote(statement, args)

    async def close(self) -> None:
        if self._client is not None:
            client = self._client
            self._client = None
            await client.close()

        if self._http_client is not None:
            client = self._http_client
            self._http_client = None
            if self._owns_http_client:
                await client.aclose()

    async def __aenter__(self) -> "TursoAdapter":
        return await self.connect()

    async def __aexit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        await self.close()

    @property
    def _requires_auth(self) -> bool:
        return not self._is_local

    @property
    def _is_local(self) -> bool:
        return urlsplit(self._database_url).scheme.lower() == "file"

    @property
    def _pipeline_url(self) -> str:
        parsed = urlsplit(self._database_url)
        if parsed.scheme.lower() == "libsql":
            parsed = parsed._replace(scheme="https")
        if parsed.scheme.lower() not in {"http", "https"}:
            raise TursoConfigurationError(
                "Remote Turso URL must use libsql://, http://, or https://"
            )
        path = parsed.path.rstrip("/")
        if not path.endswith("/v2/pipeline"):
            path = f"{path}/v2/pipeline"
        return urlunsplit(parsed._replace(path=path))

    async def _execute_remote(
        self,
        statement: libsql_client.InStatement,
        args: libsql_client.InArgs,
    ) -> libsql_client.ResultSet:
        client = self._require_http_client()
        stmt = libsql_client.Statement.convert(statement, args)
        statement_payload = {
            "sql": stmt.sql,
            "args": [],
            "named_args": [],
            "want_rows": True,
        }
        if stmt.args is not None and isinstance(stmt.args, dict):
            statement_payload["named_args"] = [
                {"name": key, "value": self._value_to_proto(value)}
                for key, value in stmt.args.items()
            ]
        elif stmt.args is not None:
            statement_payload["args"] = [self._value_to_proto(value) for value in stmt.args]

        response = await client.post(
            self._pipeline_url,
            json={
                "requests": [
                    {"type": "execute", "stmt": statement_payload},
                    {"type": "close"},
                ]
            },
        )
        if not response.is_success:
            raise libsql_client.LibsqlError(
                f"Turso returned HTTP status {response.status_code}",
                "SERVER_ERROR",
            )

        payload = response.json()
        first_result = payload["results"][0]
        if first_result["type"] == "error":
            error = first_result["error"]
            raise libsql_client.LibsqlError(
                error["message"], error.get("code") or "UNKNOWN"
            )

        result = first_result["response"]["result"]
        columns = tuple(column.get("name") or "" for column in result["cols"])
        column_indexes = {column: index for index, column in enumerate(columns)}
        rows = [
            libsql_client.Row(
                column_indexes,
                tuple(self._value_from_proto(value) for value in row),
            )
            for row in result["rows"]
        ]
        last_insert_rowid = result.get("last_insert_rowid")
        return libsql_client.ResultSet(
            columns,
            rows,
            result["affected_row_count"],
            int(last_insert_rowid) if last_insert_rowid is not None else None,
        )

    def _require_http_client(self) -> httpx.AsyncClient:
        if not self.connected or self._http_client is None:
            raise RuntimeError("TursoAdapter is not connected")
        return self._http_client

    @staticmethod
    def _value_to_proto(value: object) -> dict[str, object]:
        if isinstance(value, datetime):
            value = int(value.timestamp() * 1000)
        elif isinstance(value, bool):
            value = int(value)

        if value is None:
            return {"type": "null"}
        if isinstance(value, str):
            return {"type": "text", "value": value}
        if isinstance(value, int):
            if not -(2**63) <= value <= 2**63 - 1:
                raise OverflowError("Integer exceeds SQLite's signed 64-bit range")
            return {"type": "integer", "value": str(value)}
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("Only finite floats are supported")
            return {"type": "float", "value": value}
        try:
            encoded = base64.b64encode(bytes(memoryview(value))).decode()
        except TypeError as exc:
            raise TypeError(f"Unsupported SQL argument type: {type(value)}") from exc
        return {"type": "blob", "base64": encoded}

    @staticmethod
    def _value_from_proto(value: dict[str, object]) -> object:
        value_type = value["type"]
        if value_type == "null":
            return None
        if value_type == "text":
            return str(value["value"])
        if value_type == "integer":
            return int(str(value["value"]))
        if value_type == "float":
            return float(value["value"])
        if value_type == "blob":
            return base64.b64decode(str(value["base64"]) + "====")
        raise libsql_client.LibsqlError(
            f"Unknown Turso value type {value_type!r}", "HRANA_PROTO_ERROR"
        )

    def _require_client(self) -> libsql_client.Client:
        if not self.connected:
            raise RuntimeError("TursoAdapter is not connected")
        assert self._client is not None
        return self._client
