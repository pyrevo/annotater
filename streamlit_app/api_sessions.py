"""Per-user session state and safe upload storage for the FastAPI backend.

This module replaces the previous process-global ``_DATA_CACHE`` dictionary.
It provides two things the API endpoints need to serve more than one user
safely:

1. :class:`SessionStore` — a bounded, thread-safe, in-memory mapping from an
   opaque, server-generated session token to the request state (parsed query
   and annotation tables, and the last execution result) owned by exactly
   one session.
2. :func:`open_private_storage` — server-generated, collision-free storage
   for an uploaded file that never uses a client-supplied filename as a
   path component.

Isolation model
---------------
The session token is generated server-side with ``secrets.token_urlsafe(32)``
(256 bits of CSPRNG entropy). It is transmitted to the browser only as an
``HttpOnly`` / ``SameSite=Lax`` cookie and is never accepted as a request
parameter, path segment or body field. A request can therefore only ever
reach the state that its own cookie identifies. The token is not a signed
claim and no data is stored client-side; the token is a pure lookup key.

Session capacity is consumed lazily, on the first state write: a request
with no valid cookie (or with an unknown/expired token) is served by a
throwaway, never-stored session, so anonymous traffic — including failed
writes — allocates no session slot and cannot evict a real user's state
from the bounded store (review findings F7, N4).

Transport binding
-----------------
Over HTTPS the token rides in the ``__Host-`` prefixed cookie
(:data:`SECURE_SESSION_COOKIE_NAME`), which browsers only accept when it is
``Secure``, has ``Path=/`` and no ``Domain`` attribute, and which is scoped
to the exact issuing host. A token planted under a sibling subdomain — or
by a same-site page over a different host — cannot be presented to this
host, so the session cannot be fixedated from off-origin content (review
finding N1). Over plain HTTP (local development only) the unprefixed
:data:`SESSION_COOKIE_NAME` is used, because browsers reject ``Secure``
cookies on cleartext connections. The two names are never mixed within one
transport: over HTTPS only the prefixed cookie is read, over HTTP only the
unprefixed one.

Transport notes
---------------
- ``HttpOnly`` hides the token from JavaScript (XSS cannot read it).
- ``SameSite=Lax`` prevents the cookie from riding along on cross-site
  ``fetch``/XHR requests, which closes the CSRF path for the state-changing
  POST endpoints.
- ``Secure`` is set whenever the request is (or is proxied as) HTTPS, so the
  cookie is not sent over cleartext in production. Behind a TLS-terminating
  reverse proxy the ``X-Forwarded-Proto`` header must be forwarded (Uvicorn
  ``--proxy-headers``, the default).

Process scope and workers
-------------------------
State lives in this process's memory and is deliberately NOT shared across
processes. The bundled ``start-script.sh`` runs a single Uvicorn worker, so
this is correct for the intended SciLifeLab Serve deployment. Running with
more than one worker (``--workers N``) would route a user's follow-up
request to a worker that does not hold their state; the deployment MUST stay
single-worker until a shared store (e.g. an external cache) is introduced.
"""

from __future__ import annotations

import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

#: Cookie name carrying the opaque session token (plain-HTTP transport,
#: i.e. local development).
SESSION_COOKIE_NAME = "annotater_session"

#: Cookie name carrying the opaque session token over HTTPS. The ``__Host-``
#: prefix makes browsers enforce Secure + Path=/ + no Domain attribute and
#: scope the cookie to the exact issuing host, so off-origin or
#: sibling-subdomain content cannot present (or fixate) a session token
#: (review finding N1).
SECURE_SESSION_COOKIE_NAME = "__Host-annotater_session"

#: Idle timeout for a session's server-side state.
DEFAULT_SESSION_TTL_SECONDS = 60 * 60

#: Hard ceiling on simultaneous in-memory sessions; the least-recently-seen
#: session is evicted first so an unauthenticated flood cannot grow memory
#: without bound.
DEFAULT_MAX_SESSIONS = 256

#: A safe single-component extension: a dot followed by 1-10 alphanumerics.
#: Anything else (path separators, dots, spaces, non-ASCII, over-long) is
#: discarded, so a client filename can never influence path resolution.
_SAFE_EXTENSION = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def safe_extension(filename: Optional[str]) -> str:
    """Return the extension of ``filename`` if it is safe, else ``""``.

    The extension is preserved because the shared normalization layer uses
    the file extension to decide whether a format's own coordinate system is
    authoritative (see :mod:`streamlit_app.core.normalization`). Only the
    final suffix, validated to contain no path-separating or other
    path-relevant characters, is kept; the rest of the name is never used as
    a path.
    """
    if not filename:
        return ""
    # A backslash is a path separator on Windows; normalise before splitting.
    name = str(filename).replace("\\", "/")
    suffix = Path(name).suffix
    if _SAFE_EXTENSION.fullmatch(suffix):
        return suffix
    return ""


def open_private_storage(directory: Path, filename: Optional[str]) -> Tuple[int, Path]:
    """Create a uniquely named, server-generated file inside ``directory``.

    The client-supplied ``filename`` is never used as a path component; only
    its validated extension is preserved. ``directory`` must already exist
    and be controlled by the caller. The file is created with owner-only
    permissions (``mkstemp`` semantics). Returns an open file descriptor and
    the absolute :class:`Path`.
    """
    directory = Path(directory)
    fd, raw_path = tempfile.mkstemp(
        dir=str(directory),
        prefix="upload-",
        suffix=safe_extension(filename),
    )
    return fd, Path(raw_path)


@dataclass
class Session:
    """Server-side request state owned by exactly one session token."""

    token: str
    created_at: float
    last_seen: float
    data: Dict[str, Any] = field(default_factory=dict)


def anonymous_session() -> Session:
    """A state-less session for reads that carry no valid cookie.

    It is never registered in a :class:`SessionStore`, so anonymous traffic
    consumes no session capacity and cannot evict a real user's state from
    the bounded store (review finding F7). Endpoints must treat it as
    read-only: nothing written to it is visible to any later request.
    """
    moment = time.monotonic()
    return Session(token="", created_at=moment, last_seen=moment)


class SessionStore:
    """Bounded, thread-safe, in-memory store of per-session request state."""

    def __init__(
        self,
        ttl_seconds: float = DEFAULT_SESSION_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._ttl = float(ttl_seconds)
        self._max = int(max_sessions)
        self._sessions: Dict[str, Session] = {}
        self._lock = threading.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def _is_expired(self, session: Session, now: float) -> bool:
        return (now - session.last_seen) > self._ttl

    def _sweep_locked(self, now: float) -> None:
        stale = [t for t, s in self._sessions.items() if self._is_expired(s, now)]
        for token in stale:
            del self._sessions[token]

    def create(self, now: Optional[float] = None) -> Session:
        """Create and store a new session with an unguessable token."""
        moment = time.monotonic() if now is None else now
        token = secrets.token_urlsafe(32)
        session = Session(token=token, created_at=moment, last_seen=moment)
        with self._lock:
            self._sweep_locked(moment)
            while len(self._sessions) >= self._max:
                # Evict the least-recently-seen session (bounded memory).
                oldest = min(self._sessions.values(), key=lambda s: s.last_seen)
                del self._sessions[oldest.token]
            self._sessions[token] = session
        return session

    def get(self, token: Optional[str], now: Optional[float] = None) -> Optional[Session]:
        """Return the live session for ``token``, or ``None``.

        Expired sessions are evicted on access and reported as absent. The
        session's ``last_seen`` is refreshed (sliding idle expiry).
        """
        if not token:
            return None
        moment = time.monotonic() if now is None else now
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if self._is_expired(session, moment):
                del self._sessions[token]
                return None
            session.last_seen = moment
            return session

    def drop(self, token: str) -> None:
        """Remove one session's state without touching any other session."""
        with self._lock:
            self._sessions.pop(token, None)

    def sweep(self, now: Optional[float] = None) -> int:
        """Evict expired sessions; returns the number removed."""
        moment = time.monotonic() if now is None else now
        with self._lock:
            before = len(self._sessions)
            self._sweep_locked(moment)
            return before - len(self._sessions)

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)
