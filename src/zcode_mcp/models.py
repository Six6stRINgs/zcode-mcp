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

from .config import (
    APP_VERSION,
    CREDENTIALS_PATH,
    PROVIDER_CONFIG_PATH,
    ZCODE_V2_CONFIG,
    log,
)

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
        if not isinstance(m, dict):
            continue
        ref = m.get("ref") or {}
        if not isinstance(ref, dict):
            ref = {}
        reasoning = m.get("reasoning") or {}
        if not isinstance(reasoning, dict):
            reasoning = {}
        props = m.get("properties")
        input_format = (
            props.get("inputFormat") if isinstance(props, dict) else None
        ) or {}
        if not isinstance(input_format, dict):
            input_format = {}
        available.append(
            {
                "provider_id": ref.get("providerId"),
                "model_id": ref.get("modelId"),
                "label": m.get("label"),
                "provider_label": m.get("providerLabel"),
                "context_window": m.get("contextWindow"),
                "max_output_tokens": m.get("maxOutputTokens"),
                "reasoning_levels": [
                    l.get("value") for l in (reasoning.get("levels") or [])
                    if isinstance(l, dict)
                ],
                "default_reasoning": reasoning.get("defaultLevel"),
                "input": {
                    k: v for k, v in input_format.items()
                },
            }
        )
    return current, available


def provider_registry() -> dict[str, dict]:
    """Merged provider registry from both ZCode config layers.

    provider_config.json is the app-server layer — its provider ids are the
    ONLY ones sessions can address. config.json's ``provider`` map is the
    desktop/account layer (builtin:*, OAuth sources) whose entries exist but
    are not session-addressable. Returns ``{id: {name, origin, enabled,
    models}}``; both files are optional (empty registry when missing).
    """
    reg: dict[str, dict] = {}
    try:
        with open(PROVIDER_CONFIG_PATH, encoding="utf-8") as f:
            d = json.load(f)
        for r in ((d.get("config") or {}).get("providerConfigRules") or {}).get(
            "providerRules"
        ) or []:
            if not isinstance(r, dict):
                continue
            pid = r.get("providerId")
            if not pid:
                continue
            rcfg = r.get("config")
            if not isinstance(rcfg, dict):
                rcfg = {}
            models = rcfg.get("personalModelIds")
            reg[pid] = {
                "name": r.get("providerName") or pid,
                "origin": "provider_config",
                "enabled": True,
                "models": list(models or []),
            }
    except (OSError, ValueError, AttributeError, TypeError) as e:
        log(f"provider registry: {PROVIDER_CONFIG_PATH} unreadable ({e!r})")
    try:
        with open(ZCODE_V2_CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        for pid, p in (cfg.get("provider") or {}).items():
            if pid in reg:
                continue
            if not isinstance(p, dict):
                p = {}
            models = p.get("models")
            reg[pid] = {
                "name": p.get("name") or pid,
                "origin": "config",
                "enabled": bool(p.get("enabled", True)),
                "models": list(models.keys() if isinstance(models, dict) else []),
            }
    except (OSError, ValueError, AttributeError, TypeError) as e:
        log(f"provider registry: {ZCODE_V2_CONFIG} unreadable ({e!r})")
    return reg


def _norm_key(s: str) -> str:
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def build_provider_aliases(
    available: list[dict], registry: dict[str, dict] | None = None
) -> dict[str, list[str]]:
    """Normalized-name → provider-id candidates for name-based selectors.

    Aliases cover raw ids, ``builtin:`` suffixes, per-model providerLabel
    values and registry display names. Names shared by several providers
    resolve to multiple candidates and are reported as ambiguous on use.
    """
    reg = registry if registry is not None else provider_registry()
    aliases: dict[str, set[str]] = {}

    def add(alias: str, pid: str | None) -> None:
        if not alias or not pid:
            return
        aliases.setdefault(_norm_key(alias), set()).add(pid)

    for m in available:
        pid = m.get("provider_id")
        if not pid:
            continue
        add(pid, pid)
        if pid.startswith("builtin:"):
            add(pid.split(":", 1)[1], pid)
        add(m.get("provider_label"), pid)
    for pid, info in reg.items():
        add(pid, pid)
        # ``builtin:bigmodel-start-plan`` also answers to ``bigmodel-start-plan``
        # and ``start-plan`` — the desktop picker's own section labels for the
        # account source, which no config file carries verbatim
        if pid.startswith("builtin:"):
            rest = pid.split(":", 1)[1]
            add(rest, pid)
            parts = rest.split("-")
            for i in range(1, len(parts) - 1):
                add("-".join(parts[i:]), pid)
        add(info.get("name"), pid)
    return {k: sorted(v) for k, v in aliases.items()}


def _resolve_provider(
    provider_id: str,
    available: list[dict],
    aliases: dict[str, list[str]] | None,
    registry: dict[str, dict] | None = None,
) -> str:
    """Map a selector's provider part to a canonical providerId.

    Exact (then case-insensitive) ids pass through untouched; names resolve
    via ``aliases``. Raises when a name is unknown or ambiguous, and points
    at the desktop picker for registry providers the session layer can't
    address. ``registry`` (from :func:`provider_registry`) sharpens the
    guidance: a provider_config entry says "no models available", a disabled
    config entry says "enable it first".
    """
    ids = {m.get("provider_id") for m in available if m.get("provider_id")}
    if not provider_id or provider_id in ids:
        return provider_id
    lowered = {p.lower(): p for p in ids}
    hit = lowered.get(provider_id.lower())
    if hit:
        return hit
    if not aliases or not ids:
        # no aliases, or the catalogue is unknown (probe failed): pass the
        # id through and let the app-server validate authoritatively
        return provider_id
    candidates = aliases.get(_norm_key(provider_id)) or []
    if len(candidates) > 1:
        # a registry name shared by several providers resolves to the one
        # sessions can actually address; ambiguity only among addressable ids
        addressable = [c for c in candidates if c in ids]
        if len(addressable) == 1:
            candidates = addressable
    if len(candidates) == 1:
        pid = candidates[0]
        if pid not in ids:
            info = (registry or {}).get(pid) or {}
            if info.get("origin") == "provider_config":
                raise ValueError(
                    f"provider '{provider_id}' ({pid}) is registered in ZCode "
                    "but currently has no models available to sessions (no "
                    "models configured, or the endpoint is unreachable)"
                )
            if info.get("enabled") is False:
                raise ValueError(
                    f"provider '{provider_id}' ({pid}) exists in ZCode but is "
                    "disabled — enable it in the ZCode desktop app to make it "
                    "session-addressable"
                )
            raise ValueError(
                f"provider '{provider_id}' ({pid}) exists in ZCode but is not "
                "addressable from MCP sessions (desktop-managed account source); "
                "switch it in the ZCode desktop model picker, or add it as a "
                "custom provider to make it session-addressable"
            )
        return pid
    if len(candidates) > 1:
        msg = (
            f"ambiguous provider '{provider_id}' matches: "
            + ", ".join(sorted(candidates))
        )
        if not any(c in ids for c in candidates):
            msg += (
                "; all of them are desktop-managed account sources not "
                "addressable from MCP sessions — pick one in the ZCode "
                "desktop model picker, or select it by its full id"
            )
        raise ValueError(msg)
    raise ValueError(
        f"unknown provider '{provider_id}'; known providers: " + ", ".join(sorted(ids))
    )


def parse_model_selector(
    selector: str,
    available: list[dict],
    aliases: dict[str, list[str]] | None = None,
    registry: dict[str, dict] | None = None,
) -> dict:
    """Parse ``modelId`` / ``providerId/modelId`` / ``providerId/modelId$level``.

    The provider part may be a raw providerId (UUID or ``bigmodel-api``) or a
    display name such as ``CPA`` / ``DeepSeek`` / ``BigModel Coding Plan``
    (matched case- and punctuation-insensitively via ``aliases``). A bare
    modelId resolves against ``available`` when exactly one entry matches
    (case-insensitive); ambiguity and no-match raise ValueError with the
    matching candidates listed. When the matched entry has a default
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
        if not provider_id.strip() or not model_id.strip():
            raise ValueError(
                f"invalid model selector '{selector}': use provider/model"
            )
        selection = _selection(
            _resolve_provider(provider_id.strip(), available, aliases, registry),
            model_id.strip(),
            level,
        )
    else:
        # bare modelId: resolve against available; entries without a usable
        # model_id only match by label
        matches = [
            m for m in available
            if (isinstance(m.get("model_id"), str)
                and m["model_id"].lower() == selector.lower())
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
