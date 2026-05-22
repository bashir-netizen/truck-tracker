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
import re
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

    def find_resource_id(self):
        """Return the id of a resource we can run reports under, or None.

        Inline report templates still execute "as" some resource; the
        account's own resource is fine. Single-truck accounts have one.
        """
        params = {
            "spec": {
                "itemsType": "avl_resource",
                "propName": "sys_name",
                "propValueMask": "*",
                "sortType": "sys_name",
            },
            "force": 1,
            "flags": 1,  # base info is enough; we only need the id
            "from": 0,
            "to": 0,
        }
        resp = self.call("core/search_items", params)
        items = resp.get("items") or []
        return items[0]["id"] if items else None

    def run_table_report(self, resource_id, unit_id, ts_from, ts_to, table_type, label, columns):
        """Execute a one-table inline report and return its raw rows.

        `columns` is a comma-separated list of Wialon column ids. Only one
        report may exist per session, so we clean up before and after.
        Returns a list of row dicts (each has `c` cells and `t1`/`t2`).
        """
        template = {
            "id": 0,
            "n": label,
            "ct": "avl_unit",
            "p": "{}",
            "tbl": [{
                "n": table_type,
                "l": label,
                "c": columns,
                "cl": columns,
                "cp": "",
                "s": "[]",
                "sl": "[]",
                "sp": "",
                "filter_order": [],
                "p": "",
                "sch": {"f1": 0, "f2": 0, "t1": 0, "t2": 0, "m": 0, "y": 0, "w": 0, "fl": 0},
                "f": 0,
            }],
        }
        self.call("report/cleanup_result", {})
        try:
            resp = self.call("report/exec_report", {
                "reportResourceId": resource_id,
                "reportTemplateId": 0,
                "reportTemplate": template,
                "reportObjectId": unit_id,
                "reportObjectSecId": 0,
                "interval": {"from": int(ts_from), "to": int(ts_to), "flags": 0},
            })
            tables = (resp.get("reportResult") or {}).get("tables") or []
            if not tables:
                return []
            n_rows = tables[0].get("rows", 0)
            if not n_rows:
                return []
            return self.call("report/get_result_rows",
                             {"tableIndex": 0, "indexFrom": 0, "indexTo": n_rows})
        finally:
            self.call("report/cleanup_result", {})

    def load_positions(self, unit_id, ts_from, ts_to, page=5000):
        """Return [(t, lat, lon, speed)] for position messages in the interval.

        Loads the interval, pages through it with get_messages, then unloads.
        Messages and reports cannot share a session, so we clean up any report
        first. Only messages carrying a `pos` are returned.
        """
        self.call("report/cleanup_result", {})
        info = self.call("messages/load_interval", {
            "itemId": unit_id, "timeFrom": int(ts_from), "timeTo": int(ts_to),
            "flags": 0, "flagsMask": 0, "loadCount": 0,
        })
        count = info.get("count", 0) if isinstance(info, dict) else 0
        out = []
        try:
            idx = 0
            while idx < count:
                batch = self.call("messages/get_messages",
                                  {"indexFrom": idx, "indexTo": min(idx + page, count)})
                msgs = batch.get("messages") if isinstance(batch, dict) else batch
                if not msgs:
                    break
                for m in msgs:
                    pos = m.get("pos")
                    if pos:
                        out.append((m.get("t"), pos.get("y"), pos.get("x"), pos.get("s")))
                idx += len(msgs)
        finally:
            self.call("messages/unload", {})
        return out

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


# --------------------------------------------------------------------------
# Report cell helpers
#
# A report cell is either a plain string ("16.18 km", "-----", "0:31:13")
# or a dict {"t": text, "v": value, "y": lat, "x": lon, "u": unit_id}.
# Datetime cells carry `v` (epoch) and `y`/`x` (position at that moment);
# numeric cells arrive as text with a unit suffix.
# --------------------------------------------------------------------------

# Wialon's placeholder for "no value".
_NULLISH = {"", "-----"}


def cell_text(cell):
    """The display text of a cell, whether dict or plain string."""
    if isinstance(cell, dict):
        return cell.get("t")
    return cell


def cell_epoch(cell):
    """Epoch seconds from a datetime cell, or None."""
    if isinstance(cell, dict):
        return cell.get("v")
    return None


def cell_xy(cell):
    """(lat, lon) from a cell, or (None, None)."""
    if isinstance(cell, dict):
        return cell.get("y"), cell.get("x")
    return None, None


def num(cell):
    """Leading number in a cell's text, or None.

    "16.18 km" -> 16.18, "55 km/h" -> 55.0, "-----" -> None.
    """
    text = cell_text(cell)
    if text is None or str(text).strip() in _NULLISH:
        return None
    s = str(text).strip().replace(",", "")
    out, seen_dot = [], False
    for ch in s:
        if ch.isdigit():
            out.append(ch)
        elif ch == "." and not seen_dot:
            out.append(ch)
            seen_dot = True
        elif ch == "-" and not out:
            out.append(ch)
        else:
            break
    try:
        return float("".join(out)) if out and out != ["-"] else None
    except ValueError:
        return None


def hms_to_seconds(cell):
    """Duration text to seconds. Handles "H:MM:SS" and "D days H:MM:SS"."""
    text = cell_text(cell)
    if text is None or str(text).strip() in _NULLISH:
        return None
    s = str(text).strip()
    days = 0
    m = re.match(r"(\d+)\s*days?\s+(.*)", s)
    if m:
        days = int(m.group(1))
        s = m.group(2).strip()
    parts = s.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.insert(0, 0)
    h, mins, sec = nums[-3], nums[-2], nums[-1]
    return days * 86400 + h * 3600 + mins * 60 + sec
