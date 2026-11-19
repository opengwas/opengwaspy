import re
from importlib import resources
from pathlib import Path

import opengwaspy
from tests.conftest import LiveAPI, live_settings, read_env_file


def test_version_is_pep440() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.dev\d+)?", opengwaspy.__version__)


def test_package_is_typed() -> None:
    assert resources.files("opengwaspy").joinpath("py.typed").is_file()


def test_env_file_parsing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# comment\n\nOPENGWAS_URL=http://x:1/\nOPENGWAS_TOKEN='abc'\nnoequals\n")
    assert read_env_file(env) == {"OPENGWAS_URL": "http://x:1/", "OPENGWAS_TOKEN": "abc"}
    assert read_env_file(tmp_path / "missing") == {}


def test_live_settings_precedence(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OPENGWAS_URL=http://file/\nOPENGWAS_TOKEN=filetoken\n")
    assert live_settings({}, env) == LiveAPI("http://file", "filetoken")
    assert live_settings({"OPENGWAS_URL": "http://env"}, env) == LiveAPI("http://env", "filetoken")
    assert live_settings({}, tmp_path / "missing") is None


def test_live_settings_never_shows_token() -> None:
    assert "secret" not in repr(LiveAPI("http://x", "secret"))
