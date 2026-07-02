"""Limitation de débit en mémoire (anti force-brute) pour les routes d'authentification.

Fenêtre glissante par clé (ex. 'login:ip:1.2.3.4' ou 'login:email:x@y.z').
Suffisant pour un déploiement mono-processus (uvicorn simple) ; pour du
multi-worker il faudrait un backend partagé (table SQLite ou Redis).
"""
import time
from collections import defaultdict, deque

_BUCKETS: dict = defaultdict(deque)


def retry_after(key: str, max_attempts: int, window_seconds: int) -> int:
    """Secondes à attendre si la clé est limitée, sinon 0. Ne consomme rien."""
    now = time.monotonic()
    bucket = _BUCKETS[key]
    while bucket and bucket[0] <= now - window_seconds:
        bucket.popleft()
    if len(bucket) >= max_attempts:
        return int(bucket[0] + window_seconds - now) + 1
    return 0


def record_failure(key: str) -> None:
    _BUCKETS[key].append(time.monotonic())


def reset(key: str) -> None:
    _BUCKETS.pop(key, None)
