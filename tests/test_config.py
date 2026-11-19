import os
from pathlib import Path

import pytest

from opengwaspy.auth import DeveloperKey, NoAuth, OpenGWASToken
from opengwaspy.config import PROFILES, Config, ConfigError, config_path


@pytest.fixture
def no_file(tmp_path: Path) -> Path:
    return tmp_path / "absent.toml"


def write(path: Path, text: str, mode: int = 0o600) -> Path:
    path.write_text(text)
    path.chmod(mode)
    return path


def test_defaults(no_file: Path) -> None:
    cfg = Config.load(environ={}, config_file=no_file)
    assert cfg.base_url == PROFILES["local"]
    assert cfg.auth == NoAuth()
    assert cfg.max_in_flight == 4


def test_argument_beats_environment_beats_file(tmp_path: Path) -> None:
    file = write(tmp_path / "c.toml", 'url = "http://file:1"\ntoken = "filekey"\n')
    env = {"OPENGWAS_URL": "http://env:2", "OPENGWAS_TOKEN": "envkey"}
    assert Config.load(environ={}, config_file=file).base_url == "http://file:1"
    assert Config.load(environ={}, config_file=file).auth == DeveloperKey("filekey")
    assert Config.load(environ=env, config_file=file).base_url == "http://env:2"
    assert Config.load(environ=env, config_file=file).auth == DeveloperKey("envkey")
    cfg = Config.load("http://arg:3/", token="argkey", environ=env, config_file=file)
    assert cfg.base_url == "http://arg:3"
    assert cfg.auth == DeveloperKey("argkey")


def test_jwt_gives_opengwas_token(no_file: Path) -> None:
    cfg = Config.load(environ={"OPENGWAS_JWT": "ey.j.w"}, config_file=no_file)
    assert cfg.auth == OpenGWASToken("ey.j.w")


def test_explicit_provider_wins(no_file: Path) -> None:
    provider = OpenGWASToken("x")
    cfg = Config.load(auth=provider, environ={"OPENGWAS_TOKEN": "k"}, config_file=no_file)
    assert cfg.auth is provider


def test_both_credentials_at_one_level_is_an_error(no_file: Path) -> None:
    with pytest.raises(ConfigError, match="set only one"):
        Config.load(environ={"OPENGWAS_TOKEN": "k", "OPENGWAS_JWT": "j"}, config_file=no_file)


def test_higher_level_credential_overrides_other_kind(no_file: Path) -> None:
    cfg = Config.load(jwt="j", environ={"OPENGWAS_TOKEN": "k"}, config_file=no_file)
    assert cfg.auth == OpenGWASToken("j")


def test_profiles(no_file: Path) -> None:
    cfg = Config.load(profile="gateway", environ={}, config_file=no_file)
    assert cfg.base_url == "https://api.opengwas.io/ogdb"
    env = {"OPENGWAS_PROFILE": "gateway"}
    assert Config.load(environ=env, config_file=no_file).base_url == PROFILES["gateway"]
    # A URL at the same level beats the profile.
    env["OPENGWAS_URL"] = "http://x:1"
    assert Config.load(environ=env, config_file=no_file).base_url == "http://x:1"
    with pytest.raises(ConfigError, match="unknown profile"):
        Config.load(profile="nope", environ={}, config_file=no_file)


def test_options_pass_through(no_file: Path) -> None:
    cfg = Config.load(environ={}, config_file=no_file, timeout=5, max_in_flight=None)
    assert cfg.timeout == 5
    assert cfg.max_in_flight == 4
    assert cfg.with_options(max_attempts=2).max_attempts == 2


@pytest.mark.parametrize(
    "url", ["ftp://x", "localhost:6432", "http://", "http://x/?q=1", "http://x/#f"]
)
def test_bad_urls(url: str) -> None:
    with pytest.raises(ConfigError):
        Config(base_url=url)


@pytest.mark.parametrize(
    "field", [{"timeout": 0}, {"max_retry_wait": -1}, {"max_attempts": 0}, {"max_in_flight": 0}]
)
def test_bad_limits(field: dict[str, float]) -> None:
    with pytest.raises(ConfigError):
        Config(**field)  # type: ignore[arg-type]


def test_bad_toml(tmp_path: Path) -> None:
    file = write(tmp_path / "c.toml", "url = \n")
    with pytest.raises(ConfigError, match="cannot parse"):
        Config.load(environ={}, config_file=file)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions")
def test_readable_credential_file_warns(tmp_path: Path) -> None:
    file = write(tmp_path / "c.toml", 'token = "k"\n', mode=0o644)
    with pytest.warns(UserWarning, match="chmod 600"):
        Config.load(environ={}, config_file=file)


def test_config_path(tmp_path: Path) -> None:
    assert config_path({"OPENGWAS_CONFIG": str(tmp_path / "x.toml")}) == tmp_path / "x.toml"
    xdg = config_path({"XDG_CONFIG_HOME": str(tmp_path)})
    assert xdg == tmp_path / "opengwaspy" / "config.toml"
    assert config_path({}).name == "config.toml"
    assert config_path().name == "config.toml"


def test_load_reads_default_file_and_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path / "c.toml", 'url = "http://cfg:9"\n')
    monkeypatch.setenv("OPENGWAS_CONFIG", str(tmp_path / "c.toml"))
    for key in ("OPENGWAS_URL", "OPENGWAS_PROFILE", "OPENGWAS_TOKEN", "OPENGWAS_JWT"):
        monkeypatch.delenv(key, raising=False)
    assert Config.load().base_url == "http://cfg:9"


@pytest.mark.parametrize(
    ("base", "path", "expected"),
    [
        ("http://h:6433", "api/status", "http://h:6433/api/status"),
        ("http://h:6433", "/api/status", "http://h:6433/api/status"),
        ("https://g.io/ogdb", "api/jobs", "https://g.io/ogdb/api/jobs"),
        ("https://g.io/ogdb", "/api/jobs", "https://g.io/ogdb/api/jobs"),
        # Paths the API returns already carry the Gateway's prefix.
        ("https://g.io/ogdb", "/ogdb/api/jobs/1", "https://g.io/ogdb/api/jobs/1"),
        ("http://h:6433", "https://other/x", "https://other/x"),
    ],
)
def test_url_resolution(base: str, path: str, expected: str) -> None:
    assert Config(base_url=base).url(path) == expected
