"""
Thin wrapper around the Hydrus Network Client API.

Docs: https://hydrusnetwork.github.io/hydrus/developer_api.html
"""
from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests


class HydrusAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class HydrusFile:
    file_id: int
    hash: str
    mime: str = ""
    width: int | None = None
    height: int | None = None
    duration: float | None = None

    @property
    def is_video(self) -> bool:
        # anything with real video/audio duration goes through the media player;
        # everything else (including static and animated images) is shown as a still image.
        return self.mime.startswith("video/") or self.mime in ("application/flash", "audio/mp3", "audio/wav", "audio/ogg", "audio/flac", "audio/x-m4a")

    @property
    def is_image(self) -> bool:
        return not self.is_video


class HydrusClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    # -- low level -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        h = {}
        if self.api_key:
            h["Hydrus-Client-API-Access-Key"] = self.api_key
        return h

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise HydrusAPIError(f"Could not reach Hydrus API at {self.base_url}: {e}")
        if not resp.ok:
            raise HydrusAPIError(f"{resp.status_code} {resp.reason}: {resp.text[:300]}", resp.status_code)
        return resp.json()

    @staticmethod
    def _json_param(value: Any) -> str:
        return json.dumps(value)

    # -- connectivity ------------------------------------------------------

    def verify_access_key(self) -> dict[str, Any]:
        return self._get("/verify_access_key")

    def api_version(self) -> dict[str, Any]:
        return self._get("/api_version")

    def get_services(self) -> dict[str, Any]:
        return self._get("/get_services")

    def file_domains(self) -> list[tuple[str, str]]:
        """Returns [(display_name, service_key), ...] for local file domains."""
        data = self.get_services()
        services = data.get("services_v2") or data.get("services") or []
        out = []
        if isinstance(services, list):
            for s in services:
                type_ = s.get("type")
                # 2 = local file domain, 15 = combined local file storage, 21 = combined local file domains
                if type_ in (2, 15, 21):
                    out.append((s.get("name", "unknown"), s.get("service_key", "")))
        elif isinstance(services, dict):
            # older/legacy shape - best effort
            for name, s in services.items():
                if isinstance(s, dict) and s.get("service_type") in (2, 15, 21):
                    out.append((name, s.get("service_key", "")))
        return out

    # -- searching ---------------------------------------------------------

    def search_files(
        self,
        tags: list[str],
        sort_type: int = 2,
        sort_asc: bool = False,
        file_service_key: str | None = None,
    ) -> list[int]:
        params = {
            "tags": self._json_param(tags if tags else ["system:everything"]),
            "file_sort_type": sort_type,
            "file_sort_asc": "true" if sort_asc else "false",
            "return_file_ids": "true",
            "return_hashes": "false",
        }
        if file_service_key:
            params["file_service_key"] = file_service_key
        data = self._get("/get_files/search_files", params=params)
        return data.get("file_ids", [])

    def file_metadata(self, file_ids: list[int]) -> list[HydrusFile]:
        if not file_ids:
            return []
        params = {
            "file_ids": self._json_param(file_ids),
            "only_return_basic_information": "true",
        }
        data = self._get("/get_files/file_metadata", params=params)
        out = []
        for m in data.get("metadata", []):
            out.append(
                HydrusFile(
                    file_id=m.get("file_id"),
                    hash=m.get("hash", ""),
                    mime=m.get("mime", ""),
                    width=m.get("width"),
                    height=m.get("height"),
                    duration=m.get("duration"),
                )
            )
        return out

    # -- direct urls (for streaming straight into a media player) ---------

    def _auth_qs(self) -> str:
        if not self.api_key:
            return ""
        return "&" + urllib.parse.urlencode({"Hydrus-Client-API-Access-Key": self.api_key})

    def file_url(self, file_id: int) -> str:
        return f"{self.base_url}/get_files/file?file_id={file_id}{self._auth_qs()}"

    def thumbnail_url(self, file_id: int) -> str:
        return f"{self.base_url}/get_files/thumbnail?file_id={file_id}{self._auth_qs()}"

    def file_bytes(self, file_id: int) -> bytes:
        url = f"{self.base_url}/get_files/file"
        params = {"file_id": file_id}
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=60)
        except requests.RequestException as e:
            raise HydrusAPIError(f"Could not fetch file {file_id}: {e}")
        if not resp.ok:
            raise HydrusAPIError(f"{resp.status_code} {resp.reason} fetching file {file_id}", resp.status_code)
        return resp.content
