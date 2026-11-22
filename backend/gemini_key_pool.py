"""
backend/gemini_key_pool.py - Multi-Key Gemini API Pool, Quota & Rate Limit Manager.
Supports configuring up to 4 Google Gemini API keys with:
- Automatic failover and rotation across keys upon daily quota exhaustion or auth errors.
- Per-model quota isolation (e.g. 20 RPD limits on preview models never kill the key for 1500 RPD models).
- Independent sliding-window Rate Limiter (RPM & TPM) per key and model to prevent burst 429 stampedes.
- Accurate error parsing for Google RPC QuotaFailure, RetryInfo (retryDelay), and Retry-After headers.
- Comprehensive diagnostic routines for live and mocked environments.
"""

import os
import re
import time
import json
import logging
import datetime
import threading
import asyncio
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_pool_lock = threading.RLock()
_KEY_COOLDOWNS: Dict[str, float] = {}  # key -> timestamp until which it is exhausted
_MODEL_COOLDOWNS: Dict[Tuple[str, str], float] = {}  # (key, model) -> timestamp until which this model is cooling down
MAX_KEYS = 4

# Known default quotas for Google Gemini Free Tier
# Standard models have 15 RPM / 1,500 RPD / 1M TPM
# Preview/experimental models have 2 to 5 RPM / 20 RPD / 32k TPM
DEFAULT_MODEL_RPM: Dict[str, int] = {
    "gemini-3.5-flash-lite": 15,
    "gemini-3.1-flash-lite": 15,
    "gemini-flash-lite-latest": 15,
    "gemini-3.5-flash": 15,
    "gemini-flash-latest": 15,
    "gemini-3-flash-preview": 5,
    "gemini-3.8-flash": 2,
    "gemini-2.5-flash": 15,
    "gemini-2.5-flash-lite": 15,
}
DEFAULT_MODEL_RPD: Dict[str, int] = {
    "gemini-3.5-flash-lite": 1500,
    "gemini-3.1-flash-lite": 1500,
    "gemini-flash-lite-latest": 1500,
    "gemini-3.5-flash": 1500,
    "gemini-flash-latest": 1500,
    "gemini-3-flash-preview": 50,
    "gemini-3.8-flash": 20,
}


def mask_api_key(key: str) -> str:
    """Safely masks an API key for logs and UI display (e.g. AIzaSy...4f2D)."""
    k = (key or "").strip()
    if not k:
        return ""
    if len(k) < 6:
        return "***"
    if len(k) <= 8:
        return f"{k[:2]}...{k[-2:]}"
    return f"{k[:6]}...{k[-4:]}"


class GeminiRateLimiter:
    """
    Thread-safe & asyncio-safe sliding-window rate limiter per API key and model.
    Tracks requests per minute (RPM) and tokens per minute (TPM), preventing burst 429
    rate-limit errors by smoothly pacing outgoing requests.
    """

    _lock = threading.Lock()
    _request_windows: Dict[str, List[float]] = {}  # key -> timestamps of calls within last 60s
    _token_windows: Dict[str, List[Tuple[float, int]]] = {}  # key -> (timestamp, token_count)
    _model_retry_after: Dict[Tuple[str, str], float] = {}  # (key, model) -> retry_after timestamp
    _key_retry_after: Dict[str, float] = {}  # key -> retry_after timestamp

    @classmethod
    def reset(cls, key: Optional[str] = None) -> None:
        """Clears rate limiter history for a specific key or all keys."""
        with cls._lock:
            if key:
                k = key.strip()
                cls._request_windows.pop(k, None)
                cls._token_windows.pop(k, None)
                cls._key_retry_after.pop(k, None)
                for mk in list(cls._model_retry_after.keys()):
                    if mk[0] == k:
                        cls._model_retry_after.pop(mk, None)
            else:
                cls._request_windows.clear()
                cls._token_windows.clear()
                cls._key_retry_after.clear()
                cls._model_retry_after.clear()

    @classmethod
    def record_retry_after(cls, key: str, model: str = "", delay_seconds: float = 5.0) -> None:
        """Records an explicit Retry-After or retryDelay from Google API."""
        k = (key or "").strip()
        if not k:
            return
        target = time.time() + max(1.0, float(delay_seconds))
        with cls._lock:
            if model:
                cls._model_retry_after[(k, model.strip())] = max(
                    cls._model_retry_after.get((k, model.strip()), 0.0), target
                )
            else:
                cls._key_retry_after[k] = max(cls._key_retry_after.get(k, 0.0), target)

    @classmethod
    async def acquire(
        cls,
        key: str,
        model: str = "",
        estimated_tokens: int = 1500,
        rpm_limit: Optional[int] = None,
        tpm_limit: int = 1_000_000,
    ) -> float:
        """
        Paces incoming requests to strictly conform to RPM and TPM quotas.
        If current rate exceeds limit, asynchronously sleeps the necessary duration.
        Returns the duration (in seconds) waited.
        """
        k = (key or "").strip()
        if not k:
            return 0.0

        m_name = (model or "").strip()
        eff_rpm = rpm_limit or DEFAULT_MODEL_RPM.get(m_name, 15)
        # Add safety margin: allow slightly fewer than the hard limit to avoid edge-burst 429
        max_rpm_in_window = max(1, eff_rpm)

        total_waited = 0.0
        while True:
            now = time.time()
            wait_time = 0.0

            with cls._lock:
                # 1. Check explicit Retry-After
                key_wait = cls._key_retry_after.get(k, 0.0) - now
                mod_wait = cls._model_retry_after.get((k, m_name), 0.0) - now if m_name else 0.0
                if key_wait > 0:
                    wait_time = max(wait_time, key_wait)
                if mod_wait > 0:
                    wait_time = max(wait_time, mod_wait)

                # 2. Check sliding window RPM (calls in last 60s)
                calls = [t for t in cls._request_windows.get(k, []) if now - t < 60.0]
                cls._request_windows[k] = calls
                if len(calls) >= max_rpm_in_window:
                    oldest = calls[0]
                    rpm_delay = max(0.1, 60.0 - (now - oldest) + 0.15)
                    wait_time = max(wait_time, rpm_delay)

                # 3. Check sliding window TPM (tokens in last 60s)
                tokens = [item for item in cls._token_windows.get(k, []) if now - item[0] < 60.0]
                cls._token_windows[k] = tokens
                current_tpm = sum(t_cnt for _, t_cnt in tokens)
                if current_tpm + estimated_tokens > tpm_limit and tokens:
                    oldest_tok = tokens[0][0]
                    tpm_delay = max(0.1, 60.0 - (now - oldest_tok) + 0.15)
                    wait_time = max(wait_time, tpm_delay)

                if wait_time <= 0.0:
                    # Acquired slot!
                    cls._request_windows.setdefault(k, []).append(now)
                    cls._token_windows.setdefault(k, []).append((now, max(100, estimated_tokens)))
                    return total_waited

            # Sleep outside lock
            sleep_chunk = min(wait_time, 2.5)
            logger.debug(
                f"[RateLimiter] Pacing request for key {mask_api_key(k)} (model={m_name}): "
                f"sleeping {sleep_chunk:.2f}s (total wait: {wait_time:.2f}s)"
            )
            await asyncio.sleep(sleep_chunk)
            total_waited += sleep_chunk

    @classmethod
    def get_stats(cls, key: str) -> Dict[str, Any]:
        """Returns active rate statistics for a given API key."""
        k = (key or "").strip()
        now = time.time()
        with cls._lock:
            calls = [t for t in cls._request_windows.get(k, []) if now - t < 60.0]
            tokens = [item for item in cls._token_windows.get(k, []) if now - item[0] < 60.0]
            tpm_used = sum(t_cnt for _, t_cnt in tokens)
            retry_until = max(cls._key_retry_after.get(k, 0.0), 0.0)
            return {
                "requests_last_minute": len(calls),
                "tokens_last_minute": tpm_used,
                "is_throttled": (retry_until > now),
                "throttle_remaining_sec": max(0.0, retry_until - now),
            }


def parse_gemini_error(status: int, response_text: str) -> Dict[str, Any]:
    """
    Parses Google Gemini API HTTP error payloads with high precision:
    - Distinguishes transient burst rate-limits (RPM / retryDelay <= 60s) from daily quota exhaustion.
    - Extracts model-specific QuotaFailure dimensions (e.g. limit: 20 on gemini-3.8-flash).
    - Extracts RetryInfo retryDelay (in seconds).
    - Identifies authentication/permission errors vs 404 model sunset vs 500/503 service overloads.
    """
    raw = (response_text or "").strip()
    result: Dict[str, Any] = {
        "status": status,
        "category": "UNKNOWN",
        "message": raw[:300],
        "model": None,
        "retry_delay_sec": None,
        "quota_metric": None,
        "quota_id": None,
        "quota_value": None,
        "is_transient": False,
        "is_model_specific": False,
        "is_daily_quota": False,
    }

    parsed: Dict[str, Any] = {}
    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
        except Exception:
            pass

    err_obj = parsed.get("error", {}) if isinstance(parsed, dict) else {}
    msg = err_obj.get("message", raw) if isinstance(err_obj, dict) else raw
    err_low = (msg + " " + raw).lower()
    result["message"] = msg

    # 1. Authentication / Permission errors
    if status in (401, 403) or "api_key_invalid" in err_low or "api key not valid" in err_low:
        result["category"] = "AUTH_ERROR"
        return result

    # 2. Model deprecated / not found (404)
    if status == 404 or "is no longer available" in err_low or "not found" in err_low:
        result["category"] = "MODEL_NOT_FOUND"
        return result

    # 3. Server errors / high demand overload (500, 502, 503, 504)
    if status in (500, 502, 503, 504) or "high demand" in err_low or "temporarily unavailable" in err_low:
        result["category"] = "SERVER_ERROR"
        result["is_transient"] = True
        result["retry_delay_sec"] = 4.0
        return result

    # 4. HTTP 429 & Quota Exceeded analysis
    if status == 429 or "quota" in err_low or "rate limit" in err_low or "resource_exhausted" in err_low:
        # Check details array for structured Google RPC objects
        details = err_obj.get("details", []) if isinstance(err_obj, dict) else []
        for d in details:
            if not isinstance(d, dict):
                continue
            # Extract RetryInfo
            if "RetryInfo" in d.get("@type", "") or "retryDelay" in d:
                raw_delay = str(d.get("retryDelay", ""))
                m_sec = re.search(r"(\d+(?:\.\d+)?)s?", raw_delay)
                if m_sec:
                    try:
                        result["retry_delay_sec"] = float(m_sec.group(1))
                    except Exception:
                        pass

            # Extract QuotaFailure
            if "QuotaFailure" in d.get("@type", "") or "violations" in d:
                for v in d.get("violations", []):
                    if not isinstance(v, dict):
                        continue
                    result["quota_metric"] = v.get("quotaMetric")
                    result["quota_id"] = v.get("quotaId")
                    result["quota_value"] = v.get("quotaValue")
                    dims = v.get("quotaDimensions", {})
                    if isinstance(dims, dict) and dims.get("model"):
                        result["model"] = dims.get("model")
                        result["is_model_specific"] = True

        # Fallback regex for retryDelay in text
        if result["retry_delay_sec"] is None:
            m_delay = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', raw)
            if m_delay:
                try:
                    result["retry_delay_sec"] = float(m_delay.group(1))
                except Exception:
                    pass

        # Fallback regex for model in text
        if not result["model"]:
            m_mod = re.search(r'model:\s*([a-zA-Z0-9\.\-_]+)', raw)
            if m_mod:
                result["model"] = m_mod.group(1)
                result["is_model_specific"] = True

        # Classify Daily vs Transient:
        delay = result["retry_delay_sec"]
        qid = (result["quota_id"] or "").lower()

        # Explicit daily indicators
        has_daily_qid = "requestsperday" in qid or "daily" in qid or "perday" in qid
        has_daily_text = (
            "per day limit exceeded" in err_low
            or "requests per day" in err_low
            or "daily limit" in err_low
        )
        is_large_delay = delay is not None and delay > 120.0

        if has_daily_qid or has_daily_text or is_large_delay:
            result["is_daily_quota"] = True
            result["is_transient"] = False
            if result["is_model_specific"]:
                result["category"] = "QUOTA_EXCEEDED_DAILY_MODEL"
            else:
                result["category"] = "QUOTA_EXCEEDED_DAILY_KEY"
            return result

        # Model-specific plan/tier check
        if ("billing details" in err_low or "plan" in err_low) and not result["is_daily_quota"]:
            result["category"] = "MODEL_TIER_RESTRICTED"
            result["is_model_specific"] = True
            result["is_transient"] = False
            return result

        # If delay is <= 60s or per-minute metric, it's transient
        result["category"] = "RATE_LIMIT_TRANSIENT"
        result["is_transient"] = True
        if result["retry_delay_sec"] is None:
            result["retry_delay_sec"] = 4.0
        return result

    return result


class GeminiKeyPool:
    """
    Thread-safe pool of up to 4 Gemini API keys with:
    - Automatic per-key and per-model cooldowns
    - Seamless failover across keys
    - Circuit breaker coordination
    """

    @staticmethod
    def get_keys() -> List[str]:
        """Returns the list of configured API keys (up to MAX_KEYS), preserving order."""
        from backend.settings_manager import get_setting

        with _pool_lock:
            keys_raw = get_setting("gemini_api_keys")
            keys: List[str] = []
            if isinstance(keys_raw, list):
                for item in keys_raw:
                    if isinstance(item, str) and item.strip():
                        cleaned = item.strip()
                        if cleaned not in keys:
                            keys.append(cleaned)
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

            for stale_mk in list(_MODEL_COOLDOWNS.keys()):
                if stale_mk[0] not in cleaned_keys:
                    _MODEL_COOLDOWNS.pop(stale_mk, None)

            # If the updated pool contains at least one active (non-exhausted) key, reset global circuit breaker
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
        target = now + max(0.05, float(cooldown_seconds))
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

            # If ALL keys in pool are exhausted, trip global circuit breaker
            if not available and keys:
                earliest_target = min(_KEY_COOLDOWNS.get(cand, target) for cand in keys)
                earliest_cooldown = max(0.05, earliest_target - now)
                try:
                    from backend.ai_polisher import trip_gemini_quota_exhaustion
                    trip_gemini_quota_exhaustion(earliest_cooldown)
                except Exception:
                    pass

    @staticmethod
    def mark_model_exhausted(key: str, model: str, cooldown_seconds: float = 86400.0, reason: str = "") -> None:
        """
        Marks ONLY a specific model as exhausted for a given key.
        Prevents a model-specific quota limit (e.g. 20 RPD on gemini-3.8-flash)
        from disabling other high-quota models (e.g. 1500 RPD flash-lite) on the same key!
        """
        k = (key or "").strip()
        m = (model or "").strip()
        if not k or not m:
            return

        now = time.time()
        target = now + max(0.05, float(cooldown_seconds))
        with _pool_lock:
            _MODEL_COOLDOWNS[(k, m)] = max(_MODEL_COOLDOWNS.get((k, m), 0.0), target)
            reset_dt = datetime.datetime.fromtimestamp(target).strftime("%H:%M:%S")
            logger.warning(
                f"[Gemini Key Pool] Model '{m}' reached quota limit on key {mask_api_key(k)} "
                f"(reason: {reason or 'model daily limit'}). In cooldown until {reset_dt} ({int(cooldown_seconds)}s)."
            )

    @staticmethod
    def is_model_exhausted(key: str, model: str) -> bool:
        """Checks if a specific model on a given key is currently cooling down."""
        k = (key or "").strip()
        m = (model or "").strip()
        if not k or not m:
            return False
        with _pool_lock:
            return time.time() < _MODEL_COOLDOWNS.get((k, m), 0.0)

    @staticmethod
    def get_active_models_for_key(key: str, candidate_models: List[str]) -> List[str]:
        """Filters candidate models, returning only those not cooling down for this key."""
        k = (key or "").strip()
        now = time.time()
        with _pool_lock:
            return [m for m in candidate_models if now >= _MODEL_COOLDOWNS.get((k, m), 0.0)]

    @staticmethod
    def reset_quota(key: Optional[str] = None) -> None:
        """Resets quota exhaustion for a specific key or for all keys in the pool."""
        with _pool_lock:
            if key:
                k = key.strip()
                _KEY_COOLDOWNS.pop(k, None)
                for mk in list(_MODEL_COOLDOWNS.keys()):
                    if mk[0] == k:
                        _MODEL_COOLDOWNS.pop(mk, None)
                GeminiRateLimiter.reset(k)
            else:
                _KEY_COOLDOWNS.clear()
                _MODEL_COOLDOWNS.clear()
                GeminiRateLimiter.reset()

            try:
                from backend.ai_polisher import reset_gemini_quota_exhaustion
                reset_gemini_quota_exhaustion()
            except Exception:
                pass

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
        If at least one key is now active, resets circuit breaker and returns True.
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

            for mk in list(_MODEL_COOLDOWNS.keys()):
                if now >= _MODEL_COOLDOWNS[mk]:
                    _MODEL_COOLDOWNS.pop(mk, None)
                    expired_any = True

            available = [cand for cand in keys if now >= _KEY_COOLDOWNS.get(cand, 0.0)]
            if available:
                try:
                    from backend.ai_polisher import is_gemini_quota_exhausted, reset_gemini_quota_exhaustion
                    if is_gemini_quota_exhausted():
                        logger.info(
                            f"[Gemini Key Pool] Cooldown expired for pool keys ({len(available)}/{len(keys)} active). "
                            f"Resetting quota circuit breaker."
                        )
                        reset_gemini_quota_exhaustion()
                        return True
                except Exception:
                    pass
            return expired_any

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

                rate_stats = GeminiRateLimiter.get_stats(key)

                # Models cooling down for this key
                cooling_models = [
                    mk[1] for mk in _MODEL_COOLDOWNS.keys()
                    if mk[0] == key and now < _MODEL_COOLDOWNS[mk]
                ]

                slots.append({
                    "slot": i + 1,
                    "masked_key": mask_api_key(key),
                    "is_active": (active_idx == i),
                    "is_exhausted": is_exh,
                    "cooldown_remaining_sec": rem_sec,
                    "reset_timestamp": cooldown_until if is_exh else 0.0,
                    "reset_time_str": reset_str,
                    "rpm_last_minute": rate_stats["requests_last_minute"],
                    "tpm_last_minute": rate_stats["tokens_last_minute"],
                    "cooling_models": cooling_models,
                })

            earliest_str = (
                datetime.datetime.fromtimestamp(earliest_reset).strftime("%H:%M:%S")
                if earliest_reset > 0
                else ""
            )

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
