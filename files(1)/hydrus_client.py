"""
A small, dependency-light wrapper around the Hydrus Client API.

Official docs: https://hydrusnetwork.github.io/hydrus/developer_api.html

This only implements the handful of endpoints this viewer actually needs:
  - /verify_access_key       (sanity-check the key on startup / "Test connection")
  - /get_services            (look up the "service_key" for a tag service by name)
  - /get_files/search_files  (turn a list of tags into a list of file_ids)
  - /get_files/file_metadata (get mime type / tags / etc for a file_id)
  - /get_files/file          (download the actual file bytes)
  - /add_tags/add_tags       (add tags to a file)
"""

import json
import requests


class HydrusClientError(Exception):
    """Raised for any non-200 response or network problem talking to Hydrus."""


class HydrusClient:
    def __init__(self, base_url: str, access_key: str, timeout: float = 20.0):
        self.base_url = (base_url or "").rstrip("/")
        self.access_key = access_key or ""
        self.timeout = timeout
        self._services_cache = None

    # -- low level helpers ---------------------------------------------

    def _headers(self):
        h = {}
        if self.access_key:
            h["Hydrus-Client-API-Access-Key"] = self.access_key
        return h

    def _get(self, path, params=None):
        if not self.base_url:
            raise HydrusClientError("Hydrus API URL is not set. Open Settings (Esc) and fill it in.")
        url = f"{self.base_url}{path}"
        encoded = {}
        for k, v in (params or {}).items():
            if v is None:
                continue
            # Hydrus wants lists/dicts as JSON-encoded strings in GET params,
            # and bools as lowercase "true"/"false" rather than Python's
            # "True"/"False" - so just run everything but plain strings/ints
            # through json.dumps, and check bool before int (bool is an int
            # subclass in Python).
            if isinstance(v, bool):
                encoded[k] = "true" if v else "false"
            elif isinstance(v, (list, dict)):
                encoded[k] = json.dumps(v)
            else:
                encoded[k] = v
        try:
            resp = requests.get(url, params=encoded, headers=self._headers(), timeout=self.timeout)
        except requests.RequestException as e:
            raise HydrusClientError(f"Could not reach Hydrus at {self.base_url}: {e}") from e
        if resp.status_code != 200:
            raise HydrusClientError(self._format_error(resp))
        return resp

    def _post(self, path, body):
        if not self.base_url:
            raise HydrusClientError("Hydrus API URL is not set. Open Settings (Esc) and fill it in.")
        url = f"{self.base_url}{path}"
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise HydrusClientError(f"Could not reach Hydrus at {self.base_url}: {e}") from e
        if resp.status_code != 200:
            raise HydrusClientError(self._format_error(resp))
        return resp

    @staticmethod
    def _format_error(resp):
        text = (resp.text or "")[:400]
        hint = ""
        if resp.status_code == 401:
            hint = " (missing/invalid access key)"
        elif resp.status_code == 403:
            hint = " (this access key lacks the needed permission)"
        elif resp.status_code == 419:
            hint = " (session key expired)"
        return f"Hydrus returned {resp.status_code}{hint}: {text}"

    # -- public API ------------------------------------------------------

    def verify(self):
        """Check the access key is valid and see what permissions it has."""
        return self._get("/verify_access_key").json()

    def get_services(self):
        """Returns the list of Hydrus 'services' (tag domains, file domains, etc)."""
        if self._services_cache is None:
            data = self._get("/get_services").json()
            services = data.get("services_v2", data.get("services", []))
            if isinstance(services, dict):
                services = list(services.values())
            self._services_cache = services or []
        return self._services_cache

    def get_tag_service_key(self, service_name):
        """Look up the service_key for a tag service by its display name.
        Matches local tag domains (type 5) and tag repositories (type 0)."""
        for svc in self.get_services():
            if svc.get("name") == service_name and svc.get("type") in (0, 5):
                return svc.get("service_key")
        return None

    def search_files(self, tags):
        """Search returns file_ids only (sorted by import time, newest first,
        per Hydrus's default). We don't need hashes since file_id works fine
        for everything else we do here."""
        params = {
            "tags": tags,
            "return_file_ids": True,
            "return_hashes": False,
        }
        data = self._get("/get_files/search_files", params=params).json()
        return data.get("file_ids", [])

    def get_file_metadata(self, file_ids):
        if not file_ids:
            return []
        data = self._get("/get_files/file_metadata", params={"file_ids": file_ids}).json()
        return data.get("metadata", [])

    def get_file_bytes(self, file_id):
        if not self.base_url:
            raise HydrusClientError("Hydrus API URL is not set. Open Settings (Esc) and fill it in.")
        url = f"{self.base_url}/get_files/file"
        try:
            resp = requests.get(
                url, params={"file_id": file_id}, headers=self._headers(), timeout=max(self.timeout, 60.0)
            )
        except requests.RequestException as e:
            raise HydrusClientError(f"Could not reach Hydrus at {self.base_url}: {e}") from e
        if resp.status_code != 200:
            raise HydrusClientError(self._format_error(resp))
        return resp.content

    def add_tags(self, file_id, tag_service_key, tags):
        body = {
            "file_id": file_id,
            "service_keys_to_tags": {tag_service_key: list(tags)},
        }
        self._post("/add_tags/add_tags", body)


def extract_tag_list(metadata):
    """Pull a flat, de-duplicated, sorted list of tags out of a
    /get_files/file_metadata entry, regardless of which tag service(s)
    or current/pending/deleted/petitioned status they're under.
    This is for *display* purposes only."""
    tags_obj = metadata.get("tags") or {}
    seen = set()
    for _service_key, service_data in tags_obj.items():
        storage = (service_data or {}).get("storage_tags") or {}
        for _status_code, tag_list in storage.items():
            for t in tag_list:
                seen.add(t)
    return sorted(seen)
