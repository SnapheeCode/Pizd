from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

import httpx


@dataclass(slots=True)
class GraphQLRequest:
    operation_name: str
    query: str
    variables: Dict[str, Any]


class GraphQLClient:
    def __init__(self, base_url: str, cookie: str, user_agent: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._cookie = cookie
        self._user_agent = user_agent
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def execute(self, request: GraphQLRequest) -> Dict[str, Any]:
        payload = {
            "operationName": request.operation_name,
            "variables": request.variables,
            "query": request.query,
        }
        headers = {
            "Content-Type": "application/json",
            "Cookie": self._cookie,
            "User-Agent": self._user_agent,
        }
        async with self._lock:
            response = await self._client.post("/graphqlapi", json=[payload], headers=headers)
        response.raise_for_status()
        json_payload = response.json()
        if not json_payload:
            raise RuntimeError("Empty GraphQL response")
        first = json_payload[0]
        if "errors" in first and first["errors"]:
            raise RuntimeError(f"GraphQL error: {first['errors']}")
        return first.get("data", {})

    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> httpx.Response:
        headers = {
            "Cookie": self._cookie,
            "User-Agent": self._user_agent,
        }
        return await self._client.get(path, params=params, headers=headers)

    async def __aenter__(self) -> "GraphQLClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
