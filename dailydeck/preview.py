"""Live preview of an unsaved profile on the deck.

The editor writes a request file to the user's runtime directory; the daemon
polls it, shows the profile (without sending any shortcuts) and acknowledges
with the request's revision. The editor refreshes ``expires`` every few
seconds, so a crashed editor does not leave the deck in preview mode.
"""

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .config import ConfigError, Profile, Settings, load_profile, parse_settings

log = logging.getLogger(__name__)

REQUEST_FILE = "preview.json"
ACK_FILE = "preview.ack"
TTL = 6.0  # seconds a request stays valid without a heartbeat


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        path = Path(base) / "dailydeck"
    else:
        user = os.getuid() if hasattr(os, "getuid") else os.environ.get("USERNAME", "user")
        path = Path(tempfile.gettempdir()) / f"dailydeck-{user}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _atomic_write(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


@dataclass
class PreviewRequest:
    rev: str
    profile: Profile
    settings: Settings
    ids: tuple[str, ...]
    page: int


def make_payload(rev: str, profile: dict, settings: dict, config_dir: Path, ids, page: int) -> dict:
    return {
        "rev": rev,
        "expires": time.time() + TTL,
        "config_dir": str(config_dir),
        "settings": settings,
        "profile": profile,
        "ids": list(ids),
        "page": page,
    }


def request_from_payload(payload: dict) -> PreviewRequest:
    config_dir = Path(payload["config_dir"])
    return PreviewRequest(
        rev=str(payload["rev"]),
        profile=load_profile(payload["profile"], 0, config_dir),
        settings=parse_settings({"settings": payload.get("settings", {})}),
        ids=tuple(payload.get("ids", ())),
        page=int(payload.get("page", 0)),
    )


# ------------------------------------------------------------------ editor side

def send_request(payload: dict) -> None:
    payload["expires"] = time.time() + TTL
    _atomic_write(runtime_dir() / REQUEST_FILE, json.dumps(payload))


def clear_request() -> None:
    (runtime_dir() / REQUEST_FILE).unlink(missing_ok=True)


def read_ack() -> str | None:
    try:
        return (runtime_dir() / ACK_FILE).read_text().strip()
    except OSError:
        return None


# ------------------------------------------------------------------ daemon side

class PreviewWatcher:
    def __init__(self):
        self._path = runtime_dir() / REQUEST_FILE
        self.reset()

    def reset(self) -> None:
        """Forget the state, so an active preview is reported again (e.g. after a reconnect)."""
        self._mtime = None
        self._active: PreviewRequest | None = None
        self._expires = 0.0

    def poll(self) -> tuple[bool, PreviewRequest | None]:
        """Return (changed, active request or None)."""
        changed = False
        try:
            mtime = self._path.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            payload = self._read() if mtime is not None else None
            if payload is None:
                changed = self._active is not None
                self._active = None
            else:
                self._expires = float(payload.get("expires", 0))
                if self._active is None or str(payload.get("rev")) != self._active.rev:
                    try:
                        self._active = request_from_payload(payload)
                        changed = True
                    except (ConfigError, KeyError, TypeError, ValueError) as e:
                        log.warning("invalid preview request: %s", e)
        if self._active is not None and time.time() > self._expires:
            log.info("preview expired")
            self._active = None
            changed = True
        return changed, self._active

    def _read(self) -> dict | None:
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.debug("cannot read preview request: %s", e)
            return None

    @staticmethod
    def acknowledge(rev: str) -> None:
        try:
            _atomic_write(runtime_dir() / ACK_FILE, rev)
        except OSError as e:
            log.debug("cannot write preview ack: %s", e)
