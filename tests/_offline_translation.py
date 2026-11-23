"""
_offline_translation.py - Stand-ins for the free translation services, installed in the test sandbox.

The real services have small allowances per internet address (MyMemory: a few thousand characters a day), shared
with the user's own BookApp: one run of the suites used them up, and then failed itself. Only the translation hosts
are answered here, at transport level, so the app's own request, parsing and fallback code still runs.
BOOKAPP_LIVE_TESTS=1 tests against the real services.
"""
import asyncio
import io
import json
import os
import time
import urllib.request
from urllib.parse import parse_qsl, urlsplit

GOOGLE = "translate.googleapis.com"
MYMEMORY = "api.mymemory.translated.net"
DEEP_TRANSLATOR = "translate.google.com"
SLOW_MARKER = "slow service"  # text holding this takes as long as a busy real service (cancellation tests)

_LATIN = "abcdefghijklmnopqrstuvwxyz"
_GREEK = "αβκδεφγηιζκλμνοπθρστυβωξψζ"
_TO_GREEK = str.maketrans(_LATIN + _LATIN.upper(), _GREEK + _GREEK.upper())
_TO_LATIN = str.maketrans(_GREEK + _GREEK.upper(), _LATIN + _LATIN.upper())


def fake_translate(text: str, target: str) -> str:
    """Letter for letter: every word, number, sign and line break stays where it was, in the other script."""
    return text.translate(_TO_GREEK if target.lower().startswith("el") else _TO_LATIN)


def _delay(answer) -> float:
    return 2.0 if SLOW_MARKER in json.dumps(answer) else 0.0


def _answer(url, sent=None):
    parts = urlsplit(str(url))
    if parts.hostname not in (GOOGLE, MYMEMORY):
        return None
    fields = dict(parse_qsl(parts.query, keep_blank_values=True))
    if isinstance(sent, dict):
        fields.update(sent)
    elif sent:
        fields.update(parse_qsl(sent.decode() if isinstance(sent, bytes) else str(sent), keep_blank_values=True))
    text = fields.get("q", "")
    if parts.hostname == GOOGLE:
        return [[[fake_translate(text, fields.get("tl", "el")), text, None, None, 1]], None, fields.get("sl", "en")]
    out = fake_translate(text, fields.get("langpair", "en|el").split("|")[-1])
    return {"responseStatus": 200, "responseData": {"translatedText": out}, "quotaFinished": False,
            "matches": [{"segment": text, "translation": out, "match": 0.85, "created-by": "MT!"}]}


class _AsyncResponse:
    status = 200
    headers: dict = {}

    def __init__(self, url, data):
        self.url, self._data = url, data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def json(self, **_kw):
        return self._data

    async def text(self, **_kw):
        return json.dumps(self._data)

    def release(self):
        pass


def install() -> None:
    if os.environ.get("BOOKAPP_LIVE_TESTS") == "1" or getattr(urllib.request.urlopen, "offline_translation", False):
        return
    import aiohttp
    import requests

    real_urlopen = urllib.request.urlopen

    def urlopen(url, data=None, *args, **kwargs):
        is_request = not isinstance(url, str)
        answer = _answer(url.full_url if is_request else url, url.data if is_request and url.data else data)
        if answer is None:
            return real_urlopen(url, data, *args, **kwargs)
        time.sleep(_delay(answer))
        return io.BytesIO(json.dumps(answer).encode("utf-8"))

    urlopen.offline_translation = True
    urllib.request.urlopen = urlopen

    real_async = aiohttp.ClientSession._request

    async def request(self, method, url, *args, **kwargs):
        answer = _answer(url, kwargs.get("data") or kwargs.get("params"))
        if answer is None:
            return await real_async(self, method, url, *args, **kwargs)
        await asyncio.sleep(_delay(answer))
        return _AsyncResponse(url, answer)

    aiohttp.ClientSession._request = request

    real_sync = requests.Session.request

    def session_request(self, method, url, *args, **kwargs):
        if urlsplit(str(url)).hostname == DEEP_TRANSLATOR:
            raise requests.exceptions.ConnectionError("offline in the test sandbox")
        return real_sync(self, method, url, *args, **kwargs)

    requests.Session.request = session_request
