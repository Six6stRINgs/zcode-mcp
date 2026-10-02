"""Model listing/selection and GLM Coding Plan quota.

Model selections follow the desktop picker format
``providerId/modelId$reasoningLevel`` (see model-selection.ts in the
open-source tree); a bare ``modelId`` is resolved against the session's
available-models list when unambiguous.

Quota reads the GLM Coding Plan (Start Plan) limit endpoint with the
locally stored OAuth token, decrypting ``~/.zcode/v2/credentials.json``
exactly the way the desktop does (credentialCipherProvider.ts: AES-256-GCM,
key = sha256 of "zcode-credential-fallback:<platform>:<home>:<username>").
The token is never logged or included in any tool output.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import sys
import time
import urllib.error
import urllib.request

from .config import APP_VERSION, CREDENTIALS_PATH, ZCODE_V2_CONFIG, log

REASONING_SEPARATOR = "$"
QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"


# ---------------------------------------------------------------------------
# model selection


def _norm_session_models(snapshot: dict) -> tuple[dict | None, list[dict]]:
    """Extract (current, available) from a session state snapshot."""
    settings = (snapshot or {}).get("settings") or {}
    model = settings.get("model") or {}
    current = model.get("current") or None
    available = []
    for m in model.get("available") or []:
        ref = m.get("ref") or {}
        reasoning = m.get("reasoning") or {}
        available.append(
            {
                "provider_id": ref.get("providerId"),
                "model_id": ref.get("modelId"),
                "label": m.get("label"),
                "provider_label": m.get("providerLabel"),
                "context_window": m.get("contextWindow"),
                "max_output_tokens": m.get("maxOutputTokens"),
                "reasoning_levels": [l.get("value") for l in reasoning.get("levels") or []],
                "default_reasoning": reasoning.get("defaultLevel"),
                "input": {
                    k: v for k, v in (m.get("properties") or {}).get("inputFormat", {}).items()
                },
            }
        )
    return current, available


def parse_model_selector(selector: str, available: list[dict]) -> dict:
    """Parse ``modelId`` / ``providerId/modelId`` / ``providerId/modelId$level``.

    A bare modelId resolves against ``available`` when exactly one entry
    matches (case-insensitive); ambiguity and no-match raise ValueError with
    the matching candidates listed. When the matched entry has a default
    reasoning level and none was given, the default is applied (some models
    reject creation without one).
    """
    selector = (selector or "").strip()
    if not selector:
        raise ValueError("empty model selector")
    level = None
    if REASONING_SEPARATOR in selector:
        selector, level = selector.split(REASONING_SEPARATOR, 1)
        level = level.strip() or None
    if "/" in selector:
        provider_id, model_id = selector.split("/", 1)
        selection = _selection(provider_id.strip(), model_id.strip(), level)
    else:
        # bare modelId: resolve against available
        matches = [
            m for m in available
            if m.get("model_id", "").lower() == selector.lower()
            or (m.get("label") or "").lower() == selector.lower()
        ]
        if len(matches) == 1:
            m = matches[0]
            selection = _selection(m["provider_id"], m["model_id"], level)
        elif len(matches) > 1:
            labels = ", ".join(sorted({f"{m['provider_id']}/{m['model_id']}" for m in matches}))
            raise ValueError(
                f"ambiguous model '{selector}' matches: {labels}; use providerId/modelId"
            )
        else:
            raise ValueError(
                f"unknown model '{selector}'; call zcode_models to list available models"
            )
    if level is None and not selection.get("options"):
        entry = next(
            (
                m for m in available
                if m.get("provider_id") == selection["providerId"]
                and m.get("model_id") == selection["modelId"]
            ),
            None,
        )
        levels = (entry or {}).get("reasoning_levels") or []
        if "high" in levels:
            # project default: prefer "high" over the model's own default
            selection["options"] = {"reasoningLevel": "high"}
        elif entry and entry.get("default_reasoning"):
            selection["options"] = {"reasoningLevel": entry["default_reasoning"]}
    return selection


def _selection(provider_id: str, model_id: str, level: str | None) -> dict:
    sel: dict = {"providerId": provider_id, "modelId": model_id}
    if level:
        sel["options"] = {"reasoningLevel": level}
    return sel


# ---------------------------------------------------------------------------
# GLM Coding Plan quota


def _decrypt_credential(value: str) -> str:
    """Mirror credentialCipherProvider.ts from the open-source tree."""
    if not value.startswith("enc:v1:"):
        return value
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:
        raise RuntimeError(
            "reading the GLM Coding Plan quota requires the 'cryptography' "
            "package (pip install cryptography)"
        ) from e
    iv_b64, tag_b64, ct_b64 = value[len("enc:v1:"):].split(".")
    b64url = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    secret = (
        f"zcode-credential-fallback:{'win32' if os.name == 'nt' else os.name}:"
        f"{os.path.expanduser('~')}:{os.environ.get('USERNAME') or os.environ.get('USER', 'unknown')}"
    )
    key = hashlib.sha256(secret.encode()).digest()
    iv, tag, ct = b64url(iv_b64), b64url(tag_b64), b64url(ct_b64)
    try:
        return AESGCM(key).decrypt(iv, ct + tag, None).decode()
    except Exception as e:
        # InvalidTag has an empty str(); say what actually went wrong
        raise RuntimeError(
            f"failed to decrypt the ZCode credential (key derivation mismatch: "
            f"{e!r}); the credentials file belongs to a different user/home?"
        ) from e


def _load_token() -> str:
    try:
        with open(CREDENTIALS_PATH, encoding="utf-8") as fh:
            cred = json.load(fh)
    except OSError as e:
        raise RuntimeError(f"cannot read ZCode credentials file: {e}") from e
    for key in ("oauth:bigmodel:access_token", "zcodejwttoken"):
        raw = cred.get(key)
        if raw:
            return _decrypt_credential(raw)
    raise RuntimeError(
        f"no OAuth token found in {CREDENTIALS_PATH}; log in to the ZCode desktop app first"
    )


def _humanize_limit(limit: dict) -> dict:
    unit, number = limit.get("unit"), limit.get("number")
    if unit == 3:
        window = f"{number}-hour window"
    elif unit == 6:
        window = "weekly window"
    else:
        window = f"unit={unit} number={number}"
    out = {
        "window": window,
        "limit": limit.get("remaining", 0) + limit.get("currentValue", 0) or limit.get("usage"),
        "used": limit.get("currentValue"),
        "remaining": limit.get("remaining"),
        "percentage": limit.get("percentage"),
    }
    if limit.get("nextResetTime"):
        import time as _t

        out["next_reset"] = _t.strftime(
            "%Y-%m-%d %H:%M", _t.localtime(limit["nextResetTime"] / 1000)
        )
    return out


def fetch_quota() -> dict:
    """Fetch the GLM Coding Plan / Start Plan quota snapshot.

    Returns {"level", "limits": [...], "raw"} — the token never appears.
    """
    token = _load_token()
    req = urllib.request.Request(
        QUOTA_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:200]
        raise RuntimeError(f"quota endpoint returned HTTP {e.code}: {body}") from e
    if not payload.get("success"):
        raise RuntimeError(
            f"quota endpoint error: {payload.get('code')} {payload.get('msg')}"
        )
    data = payload.get("data") or {}
    limits = [_humanize_limit(l) for l in data.get("limits") or []]
    log("quota fetched ok")
    return {"level": data.get("level"), "limits": limits}


# ---------------------------------------------------------------------------
# Start Plan balance (ZCode Trust Build style daily token buckets)


def _desktop_headers(token: str) -> dict:
    """The exact header set the ZCode desktop sends; the gateway rejects
    requests missing X-Device-Mid with a generic 'parameter error'."""
    import locale
    mid = None
    try:
        mid = json.load(open(CREDENTIALS_PATH.replace(
            "credentials.json", "telemetry-state.json"), encoding="utf-8"
        )).get("deviceMid")
    except Exception:
        pass
    headers = {
        "User-Agent": f"ZCode/{APP_VERSION}",
        "HTTP-Referer": "https://zcode.z.ai",
        "X-Title": "Z Code@electron",
        "X-ZCode-App-Version": APP_VERSION,
        "X-Platform": f"{sys.platform}-x64" if sys.platform == "win32" else sys.platform,
        "X-Client-Language": (locale.getdefaultlocale()[0] or "unknown"),
        "X-Client-Timezone": "Asia/Hong_Kong",
        "X-Os-Category": {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux"),
        "X-Os-Version": platform.version(),
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if mid:
        headers["X-Device-Mid"] = mid
    return headers


def _start_plan_providers() -> list[dict]:
    """Start-Plan-like providers from the ZCode provider config (id, jwt, base)."""
    try:
        with open(ZCODE_V2_CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except OSError:
        return []
    out = []
    for pid, prov in (cfg.get("provider") or {}).items():
        if "start-plan" not in pid:
            continue
        options = prov.get("options") or {}
        token = options.get("apiKey")
        base = options.get("baseURL")
        if token and base:
            out.append({"id": pid, "token": token, "base": base.replace("/anthropic", "")})
    return out


def fetch_start_plan_balances() -> list[dict]:
    """Per-plan token balance buckets from /zcode-plan/billing/balance.

    Returns a list of {provider, plans, balances}; empty when no Start Plan
    provider is configured. The JWT is sent in-process, never logged.
    """
    providers = _start_plan_providers()
    results = []
    for prov in providers:
        url = f"{prov['base']}/billing/balance?app_version={APP_VERSION}"
        req = urllib.request.Request(url, headers=_desktop_headers(prov["token"]))
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:150]
            results.append({"provider": prov["id"], "error": f"HTTP {e.code}: {body}"})
            continue
        if payload.get("code") != 0:
            results.append({"provider": prov["id"], "error": payload.get("msg") or "unknown"})
            continue
        data = payload.get("data") or {}
        plan_names = {
            p.get("plan_id"): p
            for p in data.get("plans") or []
        }
        balances = []
        for b in data.get("balances") or []:
            plan = plan_names.get(b.get("plan_id")) or {}
            total = b.get("total_units")
            used = b.get("used_units")
            remaining = b.get("remaining_units")
            expires = b.get("expires_at")
            entry = {
                "model": b.get("show_name"),
                "used": used,
                "total": total,
                "remaining": remaining,
                "percentage": (
                    round(used / total * 100, 1) if isinstance(total, (int, float)) and total else None
                ),
            }
            if expires:
                entry["expires"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(expires)
                )
            balances.append(entry)
        results.append(
            {
                "provider": prov["id"],
                "plan": plan_names.get(
                    next(iter(plan_names)), {}
                ).get("name") or (data.get("plans") or [{}])[0].get("name"),
                "status": ((data.get("plans") or [{}])[0].get("status")),
                "balances": balances,
            }
        )
    return results
