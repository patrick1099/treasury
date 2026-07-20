import pytest

@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path_factory, monkeypatch):
    """Task 13 wired register/refresh into hub.hubconfig.write_config and
    hub.opencode_cfg.plan_instruction/commit_instruction, both of which fall back to
    Path.home() when not explicitly configured (HUB_HOME unset -> ~/.hub;
    OPENCODE_CONFIG unset -> ~/.config/opencode/opencode.json). Tests written for
    earlier tasks already set HUB_HOME themselves where needed, but the pre-existing
    `main(["register", ...])` / `main(["refresh", ...])` tests in test_cli.py do not --
    without this guard they would silently read, and on an "add" plan even *write*,
    into this developer's real home directory: a real ~/.hub/config.toml, and worse a
    real ~/.config/opencode/opencode.json (a file that holds plaintext secrets, per
    hub/opencode_cfg.py's own docstring). Confirmed live on this machine: that file
    exists at ~/.config/opencode/opencode.json before this guard was added.

    Force Path.home() to resolve inside tmp_path for the whole hub test suite so no
    test can ever escape into a real user profile, regardless of whether it remembers
    to monkeypatch HUB_HOME/OPENCODE_CONFIG itself. Individual tests that set HUB_HOME
    (or OPENCODE_CONFIG via DeviceProfile.paths) explicitly are unaffected -- those
    values simply take precedence over the Path.home() fallback this guard redirects.

    Uses tmp_path_factory (not tmp_path) so the fake home lives *outside* the test's
    own tmp_path -- several scaffold/vault tests use tmp_path directly as a vault root
    and assert it starts out empty; nesting a fake-home directory inside it would trip
    that emptiness check.
    """
    fake_home = tmp_path_factory.mktemp("fake_home")
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("HOME", str(fake_home))
