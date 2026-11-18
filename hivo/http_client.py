"""Small standard-library JSON HTTP client for the local Ollama API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpTransportError(OSError):
    """The HTTP endpoint could not be reached at the transport layer."""


@dataclass(frozen=True)
class JsonResponse:
    status_code: int
    text: str

    def json(self):
        return json.loads(self.text)


def request_json(url: str, *, method: str, timeout: float, payload=None, headers=None) -> JsonResponse:
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request_headers = {"Accept": "application/json", **(headers or {})}
    if body is not None:
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
            return JsonResponse(int(response.status), text)
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        return JsonResponse(int(exc.code), text)
    except (URLError, OSError, TimeoutError) as exc:
        raise HttpTransportError(str(exc)) from exc


def get_json(url: str, *, timeout: float, headers=None) -> JsonResponse:
    return request_json(url, method="GET", timeout=timeout, headers=headers)


def post_json(url: str, *, timeout: float, payload, headers=None) -> JsonResponse:
    return request_json(url, method="POST", timeout=timeout, payload=payload, headers=headers)
