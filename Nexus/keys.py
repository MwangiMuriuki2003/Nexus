"""Bring-your-own-key (BYOK) support: user-supplied cloud API keys and endpoint prefs.

Nexus can run without any cloud access, but a user may bring their own
OpenAI-compatible key (Nebius Token Factory, OpenAI, or any compatible
endpoint) instead of relying on the `NEXUS_NEBIUS_API_KEY` environment
variable. The secret itself is kept in the OS keyring (macOS Keychain,
Windows Credential Locker, Linux Secret Service) and falls back to a `0600`
file inside the data dir when no keyring backend exists — headless servers,
containers and CI usually have none.

Everything here is deliberately split in two:

* the **key** (secret)  -> `KeyStore`, OS keyring first, `~/.nexus/cloud_api_key` second
* the **endpoint prefs** (not secret) -> `CloudPrefs`, `~/.nexus/cloud.json`

`resolve_cloud_config()` merges the two with the environment-backed
`Settings`, so a key saved in the UI takes precedence over the env var and
can be picked up by a running engine via `PrivacyGate.refresh_config()`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, fields
from pathlib import Path

SERVICE_NAME = "nexus"
KEY_ID = "cloud_api_key"
KEY_FILENAME = "cloud_api_key"
PREFS_FILENAME = "cloud.json"

# Sentinel: "resolve the keyring at call time" (tests pass a real/fake module
# or None to force the file backend).
_AUTO = object()


def _os_keyring():
    """The platform keyring module, or None when it is unavailable."""
    try:
        import keyring
    except Exception:
        return None
    return keyring


class KeyStore:
    """Stores exactly one cloud API key, preferring the OS keyring.

    Writes are verified by reading back: a keyring backend that silently
    discards writes (the `null` backend) then falls through to the file
    store instead of losing the key.
    """

    def __init__(self, data_dir, keyring_module=_AUTO):
        self.data_dir = Path(data_dir)
        self._keyring_module = keyring_module

    @property
    def key_file(self) -> Path:
        return self.data_dir / KEY_FILENAME

    def _keyring(self):
        if self._keyring_module is _AUTO:
            return _os_keyring()
        return self._keyring_module  # a module-like object, or None for file only

    def get(self) -> str:
        """The stored key, or "" when none is configured."""
        keyring = self._keyring()
        if keyring is not None:
            try:
                value = keyring.get_password(SERVICE_NAME, KEY_ID)
                if value:
                    return str(value)
            except Exception:
                pass  # unusable backend -> try the file store
        try:
            return self.key_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def set(self, key: str) -> None:
        """Store `key`; an empty/blank value removes the stored key."""
        key = (key or "").strip()
        if not key:
            self.delete()
            return

        keyring = self._keyring()
        if keyring is not None:
            try:
                keyring.set_password(SERVICE_NAME, KEY_ID, key)
                if keyring.get_password(SERVICE_NAME, KEY_ID) == key:
                    self._clear_file()  # never let a stale file shadow the keyring
                    return
            except Exception:
                pass
        # No usable keyring: best-effort cleanup, then keep it in the data dir.
        self._clear_keyring()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.key_file.write_text(key + "\n", encoding="utf-8")
        os.chmod(self.key_file, 0o600)

    def delete(self) -> None:
        """Remove the key from both possible locations."""
        self._clear_keyring()
        self._clear_file()

    def is_configured(self) -> bool:
        return bool(self.get())

    def location(self) -> str:
        """Where the stored key lives: "keyring", "file", or "" when unset."""
        value = self.get()
        if not value:
            return ""
        keyring = self._keyring()
        if keyring is not None:
            try:
                if keyring.get_password(SERVICE_NAME, KEY_ID) == value:
                    return "keyring"
            except Exception:
                pass
        return "file"

    def mask(self) -> str:
        """A display-safe abbreviation (`sk-a…3456`); "" when nothing is stored."""
        value = self.get()
        if not value:
            return ""
        if len(value) < 12:
            return "•" * len(value)
        return f"{value[:4]}…{value[-4:]}"

    # -- internals ------------------------------------------------------------

    def _clear_keyring(self) -> None:
        keyring = self._keyring()
        if keyring is None:
            return
        try:
            keyring.delete_password(SERVICE_NAME, KEY_ID)
        except Exception:
            pass  # nothing stored, or no backend: the file store is authoritative

    def _clear_file(self) -> None:
        try:
            self.key_file.unlink()
        except OSError:
            pass


@dataclass
class CloudPrefs:
    """Endpoint settings chosen in Settings — not secret, stored as JSON.

    Empty `base_url`/`model` mean "use the defaults from `Settings`", so an
    untouched install behaves exactly like the environment-only setup.
    """

    provider: str = "nebius"
    base_url: str = ""
    model: str = ""

    @classmethod
    def file_for(cls, data_dir) -> Path:
        return Path(data_dir) / PREFS_FILENAME

    @classmethod
    def load(cls, data_dir) -> "CloudPrefs":
        try:
            raw = json.loads(cls.file_for(data_dir).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in raw.items() if k in known and isinstance(v, str)}
        return cls(**values)

    def save(self, data_dir) -> None:
        path = self.file_for(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def update(cls, data_dir, **changes) -> "CloudPrefs":
        """Merge `changes` into the stored prefs and persist them.

        Unknown keys, non-string values and a base URL without a scheme raise
        `ValueError` so callers can surface a validation error instead of
        persisting nonsense.
        """
        known = {f.name for f in fields(cls)}
        for key, value in changes.items():
            if key not in known:
                raise ValueError(f"unknown setting: {key}")
            if not isinstance(value, str):
                raise ValueError(f"setting '{key}' must be a string")
            if key == "base_url":
                value = value.strip()
                if value and not value.startswith(("http://", "https://")):
                    raise ValueError("base_url must start with http:// or https://")

        prefs = cls.load(data_dir)
        for key, value in changes.items():
            setattr(prefs, key, value.strip() if isinstance(value, str) else value)
        if prefs.provider == "custom" and not prefs.base_url:
            raise ValueError("a custom provider needs a base_url")
        prefs.save(data_dir)
        return prefs


@dataclass(frozen=True)
class CloudConfig:
    """The effective cloud configuration after merging prefs, key and env."""

    api_key: str
    base_url: str
    model: str
    provider: str
    key_source: str  # "keyring" | "file" | "env" | ""

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def resolve_cloud_config(settings) -> CloudConfig:
    """Merge BYOK prefs/key with the environment-backed `Settings`.

    Precedence for the secret: a key saved in Settings (keyring or file) wins,
    otherwise `NEXUS_NEBIUS_API_KEY`. Endpoint prefs override the defaults only
    when the user actually filled them in.
    """
    prefs = CloudPrefs.load(settings.data_dir)
    store = KeyStore(settings.data_dir)

    api_key = store.get()
    key_source = store.location() if api_key else ""
    if not api_key:
        env_key = settings.nebius_api_key
        # Settings declares SecretStr; stay tolerant of a plain string override.
        api_key = env_key.get_secret_value() if hasattr(env_key, "get_secret_value") else str(env_key or "")
        key_source = "env" if api_key else ""

    return CloudConfig(
        api_key=api_key,
        base_url=prefs.base_url or settings.nebius_base_url,
        model=prefs.model or settings.nebius_model,
        provider=prefs.provider,
        key_source=key_source,
    )
