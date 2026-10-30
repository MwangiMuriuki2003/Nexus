"""Bring-your-own-key storage, endpoint prefs, and the settings API."""

import contextlib
import json
import threading
import urllib.error
import urllib.request

import pytest
from pydantic import SecretStr

from Nexus.keys import CloudPrefs, KeyStore, resolve_cloud_config
from Nexus.web.server import NexusWebApp, make_server


class FakeKeyring:
    """In-memory stand-in for the `keyring` module."""

    def __init__(self):
        self.passwords = {}

    def get_password(self, service, username):
        return self.passwords.get((service, username))

    def set_password(self, service, username, password):
        self.passwords[(service, username)] = password

    def delete_password(self, service, username):
        self.passwords.pop((service, username), None)


class BrokenKeyring(FakeKeyring):
    """A machine with no usable credential store (container, CI, headless box)."""

    def get_password(self, service, username):
        raise RuntimeError("no keyring backend")

    def set_password(self, service, username, password):
        raise RuntimeError("no keyring backend")

    def delete_password(self, service, username):
        raise RuntimeError("no keyring backend")


class ReadOnlyKeyring(FakeKeyring):
    """Reads fine but cannot write — a stale value must not shadow a new key."""

    def set_password(self, service, username, password):
        raise RuntimeError("backend is read-only")


# -- KeyStore -----------------------------------------------------------------


def test_key_round_trips_through_the_keyring(tmp_path):
    store = KeyStore(tmp_path, keyring_module=FakeKeyring())

    store.set("sk-abcdef1234567890")

    assert store.get() == "sk-abcdef1234567890"
    assert store.is_configured()
    assert store.location() == "keyring"
    assert not store.key_file.exists()  # the secret never hits the disk
    # Display-safe abbreviation: never the whole secret.
    assert store.mask() == "sk-a…7890"
    assert "abcdef1234567890" not in store.mask()


def test_key_falls_back_to_a_private_file_without_a_keyring(tmp_path):
    store = KeyStore(tmp_path, keyring_module=BrokenKeyring())

    store.set("sk-personal-key-0001")

    assert store.get() == "sk-personal-key-0001"
    assert store.location() == "file"
    assert oct(store.key_file.stat().st_mode & 0o777) == "0o600"
    assert store.key_file.read_text().strip() == "sk-personal-key-0001"


def test_delete_clears_both_locations(tmp_path):
    keyring = FakeKeyring()
    store = KeyStore(tmp_path, keyring_module=keyring)
    store.set("sk-doomed-key-000000")
    store.key_file.write_text("stale copy\n")  # left behind by an earlier fallback

    store.delete()

    assert store.get() == ""
    assert store.location() == ""
    assert not store.key_file.exists()
    assert ("nexus", "cloud_api_key") not in keyring.passwords


def test_saving_a_blank_key_removes_the_stored_one(tmp_path):
    store = KeyStore(tmp_path, keyring_module=FakeKeyring())
    store.set("sk-live-key-1111111")
    store.set("   ")

    assert store.get() == ""
    assert not store.is_configured()


def test_a_new_key_replaces_a_stale_keyring_value_it_cannot_overwrite(tmp_path):
    """When the keyring can only read, the freshly saved key must win."""
    keyring = FakeKeyring()
    keyring.set_password("nexus", "cloud_api_key", "sk-old-key-000000000")
    store = KeyStore(tmp_path, keyring_module=ReadOnlyKeyring())

    store.set("sk-new-key-111111111")

    assert store.get() == "sk-new-key-111111111"
    assert "sk-old-key-000000000" not in keyring.passwords


# -- CloudPrefs ---------------------------------------------------------------


def test_endpoint_prefs_round_trip(tmp_path):
    saved = CloudPrefs.update(
        tmp_path,
        provider="custom",
        base_url="https://api.example.com/v1/",
        model="acme/large",
    )

    assert saved == CloudPrefs(
        provider="custom",
        base_url="https://api.example.com/v1/",
        model="acme/large",
    )
    assert CloudPrefs.load(tmp_path) == saved
    # Untouched fields keep their defaults on a fresh data dir.
    assert CloudPrefs.load(tmp_path / "nowhere") == CloudPrefs()


def test_prefs_tolerate_unknown_fields_from_a_newer_version(tmp_path):
    CloudPrefs.file_for(tmp_path).write_text(
        json.dumps(
            {"provider": "custom", "base_url": "https://x.test/v1", "model": "m", "extra": 1}
        )
    )

    assert CloudPrefs.load(tmp_path) == CloudPrefs(
        provider="custom", base_url="https://x.test/v1", model="m"
    )


def test_prefs_reject_a_url_without_a_scheme(tmp_path):
    with pytest.raises(ValueError, match="http"):
        CloudPrefs.update(tmp_path, base_url="api.example.com")

    assert not CloudPrefs.file_for(tmp_path).exists()  # nothing was persisted


def test_a_custom_provider_requires_a_base_url(tmp_path):
    with pytest.raises(ValueError, match="base_url"):
        CloudPrefs.update(tmp_path, provider="custom")

    with pytest.raises(ValueError, match="unknown setting"):
        CloudPrefs.update(tmp_path, temperature="0.5")


# -- resolve_cloud_config -----------------------------------------------------


def test_resolver_prefers_a_saved_key_over_the_env_var(isolated_settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: keyring)
    monkeypatch.setattr(isolated_settings, "nebius_api_key", SecretStr("env-key-000"))
    KeyStore(isolated_settings.data_dir).set("byok-key-111111")

    config = resolve_cloud_config(isolated_settings)

    assert config.api_key == "byok-key-111111"
    assert config.key_source == "keyring"
    assert config.configured
    # No prefs saved: the settings defaults still apply.
    assert config.base_url == isolated_settings.nebius_base_url
    assert config.model == isolated_settings.nebius_model


def test_resolver_falls_back_to_env_key_and_endpoint_prefs(
    isolated_settings, monkeypatch
):
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: BrokenKeyring())
    monkeypatch.setattr(isolated_settings, "nebius_api_key", SecretStr("env-key-000"))
    CloudPrefs.update(
        isolated_settings.data_dir,
        provider="custom",
        base_url="https://api.example.com/v1/",
        model="acme/large",
    )

    config = resolve_cloud_config(isolated_settings)

    assert config.api_key == "env-key-000"
    assert config.key_source == "env"
    assert config.base_url == "https://api.example.com/v1/"
    assert config.model == "acme/large"
    assert config.provider == "custom"


def test_resolver_is_local_only_when_nothing_is_configured(
    isolated_settings, monkeypatch
):
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: None)
    monkeypatch.setattr(isolated_settings, "nebius_api_key", SecretStr(""))

    config = resolve_cloud_config(isolated_settings)

    assert not config.configured
    assert config.key_source == ""
    assert config.base_url == isolated_settings.nebius_base_url
    assert config.model == isolated_settings.nebius_model


def test_privacy_gate_picks_up_a_key_saved_after_startup(
    isolated_settings, monkeypatch
):
    from Nexus.core.privacy_gate import PrivacyGate

    keyring = FakeKeyring()
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: keyring)
    monkeypatch.setattr(isolated_settings, "nebius_api_key", SecretStr(""))

    gate = PrivacyGate(isolated_settings)
    assert gate.nebius is None  # starts local-only, no key yet

    KeyStore(isolated_settings.data_dir).set("sk-saved-later-1234")
    gate.refresh_config()

    assert gate.nebius is not None
    assert gate.cloud_config.api_key == "sk-saved-later-1234"
    assert gate.cloud_config.model == isolated_settings.nebius_model


# -- /api/settings ------------------------------------------------------------


@contextlib.contextmanager
def running_server(app, token=None):
    httpd = make_server("127.0.0.1", 0, app=app, token=token)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def request(base, path, method="GET", payload=None, token=None):
    """Return (status, body) without raising on 4xx/5xx."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def test_settings_api_stores_a_key_without_ever_echoing_it(
    isolated_settings, monkeypatch
):
    keyring = FakeKeyring()
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: keyring)

    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        _, before_body = request(base, "/api/settings")
        status, body = request(
            base,
            "/api/settings",
            "POST",
            {"model": "acme/large", "api_key": "sk-mystery-secret-42"},
        )
        _, after_body = request(base, "/api/settings")
        _, status_body = request(base, "/api/status")

    before, saved, after = json.loads(before_body), json.loads(body), json.loads(after_body)
    assert before["key_configured"] is False
    assert before["local_only"] is True

    assert status == 200
    assert saved["key_configured"] is True
    assert saved["key_source"] == "keyring"
    assert saved["model"] == "acme/large"
    # The secret is only ever shown masked, in either direction.
    assert "api_key" not in saved
    assert "sk-mystery-secret-42" not in json.dumps(after) + json.dumps(saved)
    assert after["key_masked"] == "sk-m…t-42"
    assert json.loads(status_body)["local_only"] is False


def test_settings_api_can_remove_the_key(isolated_settings, monkeypatch):
    keyring = FakeKeyring()
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: keyring)

    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        request(base, "/api/settings", "POST", {"api_key": "sk-temporary-123456"})
        _, saved = request(base, "/api/settings")
        assert json.loads(saved)["key_configured"] is True

        status, body = request(base, "/api/settings", "POST", {"remove_key": True})
        _, after = request(base, "/api/settings")

    assert status == 200
    assert json.loads(body)["key_configured"] is False
    assert json.loads(after)["local_only"] is True


def test_settings_api_rejects_bad_input(isolated_settings):
    app = NexusWebApp(settings=isolated_settings)
    with running_server(app) as base:
        _, bad_url = request(base, "/api/settings", "POST", {"base_url": "not-a-url"})
        _, unknown = request(base, "/api/settings", "POST", {"nope": 1})
        _, not_object = request(base, "/api/settings", "POST", ["list"])
        _, bad_type = request(base, "/api/settings", "POST", {"model": 7})

    assert "http://" in json.loads(bad_url)["error"]
    assert "nothing to update" in json.loads(unknown)["error"]
    assert "JSON object" in json.loads(not_object)["error"]
    assert "must be a string" in json.loads(bad_type)["error"]
    assert not CloudPrefs.file_for(isolated_settings.data_dir).exists()


def test_settings_api_requires_the_bearer_token_when_set(isolated_settings):
    app = NexusWebApp(settings=isolated_settings)
    with running_server(app, token="sekret") as base:
        denied, _ = request(base, "/api/settings")
        post_denied, _ = request(base, "/api/settings", "POST", {"model": "m"})
        granted, body = request(
            base, "/api/settings", "POST", {"model": "m"}, token="sekret"
        )

    assert denied == 401
    assert post_denied == 401
    assert granted == 200
    assert json.loads(body)["model"] == "m"


def test_settings_update_refreshes_a_running_engine(isolated_settings, monkeypatch):
    """A key saved over HTTP reaches the already-built privacy gate."""
    keyring = FakeKeyring()
    monkeypatch.setattr("Nexus.keys._os_keyring", lambda: keyring)

    class _Gate:
        def __init__(self):
            self.refreshes = 0

        def refresh_config(self):
            self.refreshes += 1

    class _Engine:
        def __init__(self):
            self.privacy_gate = _Gate()

    engine = _Engine()
    app = NexusWebApp(settings=isolated_settings, engine=engine)
    try:
        with running_server(app) as base:
            status, _ = request(base, "/api/settings", "POST", {"api_key": "sk-live-1"})
    finally:
        app.close()

    assert status == 200
    assert engine.privacy_gate.refreshes == 1
