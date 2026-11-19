import json
import os
import stat
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest
import respx

import opengwaspy.client as client_module
import opengwaspy.compat as compat
from opengwaspy.config import Config, ConfigError, save_setting
from opengwaspy.errors import NotImplementedByServer, RequestError
from tests.fakes import fake_client

BASE = "http://api.test"


@pytest.fixture(autouse=True)
def default_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(client_module, "_default", fake_client(BASE))
    monkeypatch.setenv("OPENGWAS_CONFIG", str(tmp_path / "config.toml"))
    for key in ("OPENGWAS_URL", "OPENGWAS_PROFILE", "OPENGWAS_TOKEN", "OPENGWAS_JWT"):
        monkeypatch.delenv(key, raising=False)


def test_ieugwas_columns() -> None:
    frame = pd.DataFrame(
        {
            "store_id": ["OGS-1"],
            "analysis_id": ["A"],
            "analysis_label": ["Height"],
            "alid": ["1:5:A:G"],
            "chromosome": ["1"],
            "position": [5],
            "rsid": ["rs1"],
            "effect_allele": ["A"],
            "other_allele": ["G"],
            "eaf": [0.2],
            "z": [4.0],
            "se": [0.5],
            "log10_p": [-4.2],
        }
    )
    out = compat.ieugwas_columns(frame, sample_sizes={"OGS-1:A": 1000})
    assert list(out.columns[:12]) == [
        "id",
        "trait",
        "rsid",
        "chr",
        "position",
        "ea",
        "nea",
        "eaf",
        "beta",
        "se",
        "p",
        "n",
    ]
    row = out.iloc[0]
    assert (row["id"], row["trait"], row["ea"], row["nea"], row["n"]) == (
        "OGS-1:A",
        "Height",
        "A",
        "G",
        1000,
    )
    assert row["beta"] == pytest.approx(2.0) and row["p"] == pytest.approx(10**-4.2)
    assert "analysis_label" in out.columns and "z" in out.columns
    assert set(compat.DERIVED) == {"beta", "p", "n"}
    assert compat.ieugwas_columns(pd.DataFrame()).empty


def test_ieugwas_columns_keeps_existing_p_and_handles_missing_ids() -> None:
    out = compat.ieugwas_columns(
        pd.DataFrame(
            {"analysis_id": ["A"], "store_id": [None], "id": ["x"], "p": [0.5], "log10_p": [-1.0]}
        ),
        {},
    )
    assert out.iloc[0]["p"] == 0.5 and out.iloc[0]["id"] == "x"


def test_legacy_ids() -> None:
    assert compat.legacy_ids(["UKB-a:100", "IEU-a:2", "ieu-b-1"]) == [
        "ukb-a-100",
        "ieu-a-2",
        "ieu-b-1",
    ]


@respx.mock
def test_status_user(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get(f"{BASE}/api/status").respond(json={"ready": True})
    respx.get(f"{BASE}/api/user").respond(json={"role": "developer"})
    assert compat.status()["ready"] and compat.user()["role"] == "developer"


@respx.mock
def test_select_api(capsys: pytest.CaptureFixture[str]) -> None:
    respx.get("http://localhost:6432/api/status").respond(json={"ready": True})
    respx.get("http://other.test/api/status").respond(json={"ready": "url"})
    assert compat.select_api("dev") == {"ready": True}
    assert "API server is now: http://localhost:6432" in capsys.readouterr().out
    assert compat.select_api("http://other.test") == {"ready": "url"}
    assert compat.select_api("private") is None
    assert "Please select one" in capsys.readouterr().out


def test_get_jwt_saves_private_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[str] = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    monkeypatch.setattr("builtins.input", lambda prompt: " ey.abc.def ")
    save_setting("token", "old-dev-key")
    compat.get_jwt()
    path = tmp_path / "config.toml"
    assert opened == ["https://api.opengwas.io/profile/"]
    assert path.read_text() == 'jwt = "ey.abc.def"\n'
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert Config.load().auth.headers() == {"Authorization": "Bearer ey.abc.def"}
    assert "saved to" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    compat.get_jwt()
    assert "nothing saved" in capsys.readouterr().out


def test_save_setting_escapes_and_validates(tmp_path: Path) -> None:
    import tomli as tomllib

    path = save_setting("url", 'http://x/"q"\\', tmp_path / "sub" / "c.toml")
    save_setting("token", "k", path)
    with path.open("rb") as fh:
        assert tomllib.load(fh) == {"url": 'http://x/"q"\\', "token": "k"}
    with pytest.raises(ConfigError):
        save_setting("password", "x", tmp_path / "c.toml")


@respx.mock
def test_gwasinfo_adds_trait_and_reports_missing(capsys: pytest.CaptureFixture[str]) -> None:
    route = respx.post(f"{BASE}/api/gwasinfo").respond(
        json={
            "analyses": [{"id": "OGS-1:A", "store_id": "OGS-1", "analysis_label": "Height"}],
            "not_found": ["ieu-a-2"],
        }
    )
    frame = compat.gwasinfo(["OGS-1:A", "IEU-a:2"])
    assert json.loads(route.calls.last.request.content)["id"] == ["OGS-1:A", "ieu-a-2"]
    assert list(frame.columns[:2]) == ["id", "trait"] and frame.iloc[0]["trait"] == "Height"
    assert "1 IDs are not served by the Data API: ieu-a-2" in capsys.readouterr().out
    compat.gwasinfo("OGS-1:A")


@respx.mock
def test_gwasinfo_lists_everything_without_ids() -> None:
    respx.get(f"{BASE}/api/gwasinfo").respond(json={"analyses": [], "next_after": None, "total": 0})
    assert compat.gwasinfo().empty


@respx.mock
def test_gwasinfo_files() -> None:
    respx.get(f"{BASE}/api/batches").respond(
        json={"batches": [{"store_id": "OGS-1", "release_id": "r1"}]}
    )
    respx.post(f"{BASE}/api/gwasinfo").mock(
        side_effect=[
            httpx.Response(200, json={"analyses": [{"id": "OGS-1:A", "store_id": "OGS-1"}]}),
            httpx.Response(200, json={"analyses": [], "not_found": ["x"]}),
        ]
    )
    files = respx.post(f"{BASE}/api/gwasinfo/files").respond(501, text="Not yet implemented")
    with pytest.raises(NotImplementedByServer):
        compat.gwasinfo_files("OGS-1:A")
    body: dict[str, Any] = json.loads(files.calls.last.request.content)
    assert body["releases"] == [{"store_id": "OGS-1", "release_id": "r1"}]
    with pytest.raises(RequestError):
        compat.gwasinfo_files(["x"])
