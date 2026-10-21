"""Guarded HTTP and cursor handling shared by the two export collectors."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, ClassVar

from security_lakehouse import netguard
from security_lakehouse.ingestion import backoff
from security_lakehouse.ingestion.paginate import object_rows, paginate


class CursorExportClient:
    item_keys: ClassVar[tuple[str, ...]]
    item_label: ClassVar[str]
    error_label: ClassVar[str]
    url_label: ClassVar[str]
    max_pages = 10_000

    def __init__(self, host: str, *, token: str, timeout: int = 30) -> None:
        self.base_url = host.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _fetch_json(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "accept": "application/json",
                "authorization": f"Bearer {self.token}",
                "user-agent": "grc-lake",
            },
        )

        def _fetch() -> Any:
            with netguard.open_public(request, timeout=self.timeout, label=self.url_label) as resp:
                return json.loads(resp.read().decode("utf-8"))

        try:
            # Retry transient 429/5xx (honoring Retry-After); a terminal 4xx or an
            # exhausted retry surfaces as a sanitized error rather than failing loud.
            return backoff.http_retry(_fetch)
        except urllib.error.HTTPError as exc:  # pragma: no cover - live only
            raise ValueError(exc.__class__.__name__) from exc

    @classmethod
    def _extract_items(cls, payload: Any, url: str) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return object_rows(payload, label=cls.item_label)
        if isinstance(payload, dict):
            for key in cls.item_keys:
                value = payload.get(key)
                if isinstance(value, list):
                    return object_rows(value, label=cls.item_label)
        raise ValueError(f"{cls.error_label} returned non-list JSON for {url}")

    def _json_list(self, url: str) -> list[dict[str, Any]]:
        return self._extract_items(self._fetch_json(url), url)

    def _json_list_paginated(self, base_url: str, params: dict[str, str]) -> list[dict[str, Any]]:
        """Follow the export's ``next_cursor`` envelope until it is exhausted.

        A server that returns a bare list (or an object without ``next_cursor``)
        yields exactly one page — so this is backward compatible with an export
        that does not paginate. ``since`` and any other params ride on every page.
        """

        def fetch_page(cursor: str | None) -> tuple[str, Any]:
            query = dict(params)
            if cursor:
                query["cursor"] = cursor
            url = f"{base_url}?{urllib.parse.urlencode(query)}" if query else base_url
            return url, self._fetch_json(url)

        def extract_items(page: tuple[str, Any]) -> list[dict[str, Any]]:
            url, payload = page
            return self._extract_items(payload, url)

        def next_cursor(page: tuple[str, Any]) -> str | None:
            _url, payload = page
            if isinstance(payload, dict):
                return str(payload.get("next_cursor") or "") or None
            return None

        return list(paginate(fetch_page, extract_items, next_cursor, max_pages=self.max_pages))
