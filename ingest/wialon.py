"""Wialon Hosting remote-API client.

This is the SINGLE choke point for every Wialon call. All retry logic,
error handling, and rate-limit backoff live here, never at the call
sites. Nothing outside this module talks to Wialon.

Protocol (verified against the official SDK docs):
  - All calls POST to {host}/wialon/ajax.html with a form body of
    `svc`, `params` (a JSON-encoded string), and `sid`.
  - token/login returns the session id in field `eid`; we send it as
    `sid` on every later call. Sessions die after ~5 min idle, so we
    re-login per run and re-login once on error 1.
  - Every response carries an integer `error` field; 0 means success.

Stage 1 implements: login, call, find_unit. Report helpers
(find_report, exec_report_tables) arrive in Stage 2.
"""

import json
import time

import requests

# Human-readable meanings for the error codes we expect to see.
ERROR_MESSAGES = {
    1: "invalid session",
    4: "invalid input",
    5: "server error performing request",
    7: "access denied — token scope too narrow",
    8: "invalid user or token",
    1003: "only one request allowed at a time",
}

# core/search_items flags for a unit (avl_unit):
#   1    base / general properties
#   1024 last message and position
#   4096 sensors
#   8192 counters (mileage `cnm`, engine hours `cneh`)
UNIT_FLAGS = 1 | 1024 | 4096 | 8192  # = 13313


class WialonError(Exception):
    """A non-zero `error` field returned by the Wialon API."""

    def __init__(self, code, svc):
        self.code = code
        self.svc = svc
        meaning = ERROR_MESSAGES.get(code, "unknown error")
        super().__init__(f"Wialon error {code} ({meaning}) on svc={svc}")


class WialonClient:
    def __init__(self, token, host="https://hst-api.wialon.eu",
                 session=None, max_retries=3, timeout=120):
        self.token = token
        self.host = host.rstrip("/")
        self.url = f"{self.host}/wialon/ajax.html"
        self.http = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout
        self.sid = None
        self.user_id = None
        self.server_time = None

    # -- public API --------------------------------------------------------

    def login(self):
        """Open a session. Stores sid (`eid`), user id, and server time."""
        resp = self._post("token/login", {"token": self.token}, with_sid=False)
        self.sid = resp["eid"]
        self.user_id = (resp.get("user") or {}).get("id")
        self.server_time = resp.get("tm")
        return resp

    def call(self, svc, params=None):
        """Call any service, logging in first if needed."""
        if self.sid is None:
            self.login()
        return self._post(svc, params or {}, with_sid=True)

    def find_unit(self, name_mask):
        """Return the first unit whose name matches `name_mask`, or None.

        The returned dict includes `pos` (last position), `cnm` (mileage,
        km) and `cneh` (engine hours, h) thanks to UNIT_FLAGS.
        """
        params = {
            "spec": {
                "itemsType": "avl_unit",
                "propName": "sys_name",
                "propValueMask": name_mask,
                "sortType": "sys_name",
            },
            "force": 1,
            "flags": UNIT_FLAGS,
            "from": 0,
            "to": 0,
        }
        resp = self.call("core/search_items", params)
        items = resp.get("items") or []
        return items[0] if items else None

    # -- transport ---------------------------------------------------------

    def _post(self, svc, params, with_sid):
        body = {"svc": svc, "params": json.dumps(params)}
        if with_sid:
            body["sid"] = self.sid

        relogged = False
        last_error = None
        for attempt in range(self.max_retries):
            r = self.http.post(self.url, data=body, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            error = data.get("error", 0) if isinstance(data, dict) else 0
            if not error:
                return data
            last_error = error

            # Invalid session: re-login once and retry with a fresh sid.
            if error == 1 and with_sid and not relogged:
                self.login()
                body["sid"] = self.sid
                relogged = True
                continue
            # Only one request at a time: brief backoff and retry.
            if error == 1003:
                time.sleep(0.5 * (attempt + 1))
                continue
            # Transient server error: exponential-ish backoff and retry.
            if error == 5:
                time.sleep(1.0 * (attempt + 1))
                continue
            # 4 (bad input), 7 (scope), 8 (bad token), or anything else: fatal.
            raise WialonError(error, svc)

        raise WialonError(last_error, svc)
