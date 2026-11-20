"""
backend/gemini_key_pool.py - Multi-Key Gemini API Pool & Failover Manager.
Supports configuring up to 4 Google Gemini API keys with automatic failover/rotation
when any key hits daily quota or 429 rate limit.
"""

import os
import time
import logging
import datetime
import threading
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_pool_lock = threading.RLock()
_KEY_COOLDOWNS: Dict[str, float] = {}  # key -> timestamp until which it is exhausted
MAX_KEYS = 4


def mask_api_key(key: str) -> str:
    """Safely masks an API key for logs and UI display (e.g. AIzaSy...4f2D)."""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) <= 8:
        return f"{k[:2]}...{k[-2:]}" if len(k) >= 4 else "***"
    return f"{k[:6]}...{k[-4:]}"


class GeminiKeyPool:
    """Thread-safe pool of up to 4 Gemini API keys with automatic quota rotation."""

    @staticmethod
    def get_keys() -> List[str]:
        """Returns the list of configured API keys (up to MAX_KEYS), preserving order."""
        from backend.settings_manager import get_setting

        with _pool_lock:
            # 1. Prefer explicit list in settings
            keys_raw = get_setting("gemini_api_keys")
            keys: List[str] = []
            if isinstance(keys_raw, list):
                for item in keys_raw:
                    if isinstance(item, str) and item.strip():
                        cleaned = item.strip()
                        if cleaned not in keys:
                            keys.append(cleaned)
            # 2. Fall back to legacy single key or environment variable
            if not keys:
                single = (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()
                if single:
                    keys.append(single)

            return keys[:MAX_KEYS]

    @staticmethod
    def set_keys(keys_input: List[str]) -> List[str]:
        """Validates, deduplicates, and saves up to MAX_KEYS to settings.json."""
        from backend.settings_manager import save_setting, delete_setting

        with _pool_lock:
            cleaned_keys: List[str] = []
            for k in keys_input or []:
                if isinstance(k, str) and k.strip():
                    c = k.strip()
                    if c not in cleaned_keys:
                        cleaned_keys.append(c)
            cleaned_keys = cleaned_keys[:MAX_KEYS]

            save_setting("gemini_api_keys", cleaned_keys)
            primary_key = cleaned_keys[0] if cleaned_keys else ""
            if primary_key:
                save_setting("gemini_api_key", primary_key)
            else:
                delete_setting("gemini_api_key")

            # Prune cooldown entries for keys no longer in the pool
            for stale_key in list(_KEY_COOLDOWNS.keys()):
                if stale_key not in cleaned_keys:
                    _KEY_COOLDOWNS.pop(stale_key, None)

            # If the updated pool contains at least one active (non-exhausted) key, reset the global circuit breaker
            now = time.time()
            if any(now >= _KEY_COOLDOWNS.get(k, 0.0) for k in cleaned_keys):
                try:
                    from backend.ai_polisher import reset_gemini_quota_exhaustion
                    reset_gemini_quota_exhaustion()
                except Exception:
                    pass

            return cleaned_keys

    @staticmethod
    def add_key(key: str) -> List[str]:
        """Appends a new key to the pool if slot is available."""
        with _pool_lock:
            keys = GeminiKeyPool.get_keys()
            k = (key or "").strip()
            if not k or k in keys:
                return keys
            if len(keys) >= MAX_KEYS:
                raise ValueError(f"Maximum limit of {MAX_KEYS} Gemini API keys reached.")
            keys.append(k)
            return GeminiKeyPool.set_keys(keys)

    @staticmethod
    def remove_key(index_or_key: Any) -> List[str]:
        """Removes a key by index (0-based) or by exact key value."""
        with _pool_lock:
            keys = GeminiKeyPool.get_keys()
            if isinstance(index_or_key, int):
                if 0 <= index_or_key < len(keys):
                    keys.pop(index_or_key)
            elif isinstance(index_or_key, str):
                cleaned = index_or_key.strip()
                keys = [k for k in keys if k != cleaned]
            return GeminiKeyPool.set_keys(keys)

    @staticmethod
    def get_active_key(exclude_keys: Optional[Set[str]] = None) -> Optional[str]:
        """Returns the first non-exhausted key from the pool, or None if all are cooling down."""
        now = time.time()
        exclude = exclude_keys or set()
        with _pool_lock:
            keys = GeminiKeyPool.get_keys()
            for key in keys:
                if key in exclude:
                    continue
                cooldown_until = _KEY_COOLDOWNS.get(key, 0.0)
                if now >= cooldown_until:
                    return key
            return None

    @staticmethod
    def mark_key_exhausted(key: str, cooldown_seconds: float = 3600.0, reason: str = "") -> None:
        """Marks a specific key as exhausted for cooldown_seconds and checks pool status."""
        k = (key or "").strip()
        if not k:
            return

        now = time.time()
        target = now + max(10.0, cooldown_seconds)
        with _pool_lock:
            _KEY_COOLDOWNS[k] = max(_KEY_COOLDOWNS.get(k, 0.0), target)

            keys = GeminiKeyPool.get_keys()
            available = [cand for cand in keys if now >= _KEY_COOLDOWNS.get(cand, 0.0)]
            masked = mask_api_key(k)
            reset_dt = datetime.datetime.fromtimestamp(target).strftime("%H:%M:%S")

            logger.warning(
                f"[Gemini Key Pool] Key {masked} reached quota/limit (reason: {reason or '429/quota'}). "
                f"Cooldown active until {reset_dt} ({int(cooldown_seconds)}s). "
                f"Remaining active keys in pool: {len(available)}/{len(keys)}."
            )

            # If ALL keys in pool are exhausted, trip the global circuit breaker with the earliest reset time
            if not available and keys:
                earliest_target = min(_KEY_COOLDOWNS.get(cand, target) for cand in keys)
                earliest_cooldown = max(10.0, earliest_target - now)
                from backend.ai_polisher import trip_gemini_quota_exhaustion
                trip_gemini_quota_exhaustion(earliest_cooldown)

    @staticmethod
    def mark_all_exhausted(cooldown_seconds: float = 3600.0) -> None:
        """Marks all currently configured keys in the pool as exhausted for cooldown_seconds."""
        now = time.time()
        target = now + max(10.0, cooldown_seconds)
        with _pool_lock:
            for k in GeminiKeyPool.get_keys():
                _KEY_COOLDOWNS[k] = max(_KEY_COOLDOWNS.get(k, 0.0), target)

    @staticmethod
    def reset_quota(key: Optional[str] = None) -> None:
        """Resets quota exhaustion for a specific key or for all keys in the pool."""
        with _pool_lock:
            if key:
                k = key.strip()
                _KEY_COOLDOWNS.pop(k, None)
            else:
                _KEY_COOLDOWNS.clear()
            from backend.ai_polisher import reset_gemini_quota_exhaustion
            reset_gemini_quota_exhaustion()

    @staticmethod
    def is_key_exhausted(key: str) -> bool:
        """Checks if a specific key is currently in cooldown."""
        with _pool_lock:
            k = (key or "").strip()
            if not k:
                return False
            return time.time() < _KEY_COOLDOWNS.get(k, 0.0)

    @staticmethod
    def check_cooldowns() -> bool:
        """
        Checks if any exhausted keys in the pool have their cooldown expired.
        If at least one key is now active, resets the circuit breaker and returns True.
        """
        now = time.time()
        with _pool_lock:
            keys = GeminiKeyPool.get_keys()
            if not keys:
                return False
            expired_any = False
            for k in list(_KEY_COOLDOWNS.keys()):
                if now >= _KEY_COOLDOWNS[k]:
                    _KEY_COOLDOWNS.pop(k, None)
                    expired_any = True

            available = [cand for cand in keys if now >= _KEY_COOLDOWNS.get(cand, 0.0)]
            if available:
                from backend.ai_polisher import is_gemini_quota_exhausted, reset_gemini_quota_exhaustion
                if is_gemini_quota_exhausted():
                    logger.info(
                        f"[Gemini Key Pool] Cooldown expired for pool keys ({len(available)}/{len(keys)} active). Resetting quota circuit breaker."
                    )
                    reset_gemini_quota_exhaustion()
                    return True
            return False

    @staticmethod
    def get_pool_status() -> Dict[str, Any]:
        """Returns full diagnostics of all pool slots for the UI and monitoring."""
        now = time.time()
        with _pool_lock:
            keys = GeminiKeyPool.get_keys()
            slots: List[Dict[str, Any]] = []
            active_idx = -1
            available_count = 0
            earliest_reset = 0.0

            for i, key in enumerate(keys):
                cooldown_until = _KEY_COOLDOWNS.get(key, 0.0)
                is_exh = now < cooldown_until
                rem_sec = int(max(0, cooldown_until - now)) if is_exh else 0
                reset_str = datetime.datetime.fromtimestamp(cooldown_until).strftime("%H:%M:%S") if is_exh else ""

                if not is_exh:
                    available_count += 1
                    if active_idx == -1:
                        active_idx = i
                else:
                    if earliest_reset == 0.0 or cooldown_until < earliest_reset:
                        earliest_reset = cooldown_until

                slots.append({
                    "slot": i + 1,
                    "masked_key": mask_api_key(key),
                    "is_active": (active_idx == i),
                    "is_exhausted": is_exh,
                    "cooldown_remaining_sec": rem_sec,
                    "reset_timestamp": cooldown_until if is_exh else 0.0,
                    "reset_time_str": reset_str,
                })

            earliest_str = datetime.datetime.fromtimestamp(earliest_reset).strftime("%H:%M:%S") if earliest_reset > 0 else ""

            return {
                "total_keys": len(keys),
                "max_keys": MAX_KEYS,
                "available_keys": available_count,
                "active_key_index": active_idx,
                "all_exhausted": (len(keys) > 0 and available_count == 0),
                "earliest_reset_timestamp": earliest_reset,
                "earliest_reset_time_str": earliest_str,
                "slots": slots,
            }


def resolve_gemini_api_key(explicit_key: Optional[str] = None) -> str:
    """
    Resolves an active Gemini API key from explicit argument, the 4-key pool,
    legacy setting, or environment variable. Returns empty string if none configured.
    """
    k = (explicit_key or "").strip()
    if k:
        return k
    active = GeminiKeyPool.get_active_key()
    if active:
        return active
    keys = GeminiKeyPool.get_keys()
    if keys:
        return keys[0]
    from backend.settings_manager import get_setting
    return (get_setting("gemini_api_key", "") or "").strip() or os.environ.get("GEMINI_API_KEY", "").strip()

