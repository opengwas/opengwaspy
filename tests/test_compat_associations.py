import json
from typing import Any

import httpx
import pytest
import respx

import opengwaspy.client as client_module
import opengwaspy.compat as compat
from tests.fakes import JobServer, fake_client

BASE = "http://api.test"
A, B = "OGS-1:A", "OGS-1:B"  # A is EUR; B is an ancestry with no LD store


@pytest.fixture(autouse=True)
def default_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_default", fake_client(BASE))


def assoc(analysis: str, alid: str, rsid: str, eaf: float = 0.2, z: float = 5.0) -> dict[str, Any]:
    ea, nea = alid.split(":")[2:]
    return {
        "store_id": "OGS-1",
        "analysis_id": analysis.split(":")[1],
        "alid": alid,
        "rsid": rsid,
        "effect_allele": ea,
        "other_allele": nea,
        "eaf": eaf,
        "z": z,
        "se": 0.1,
        "log10_p": -6.0,
    }


# What each analysis holds. The target 1:100:A:G (rs100) is in neither.
HELD = {
    A: [
        assoc(A, "1:500:C:T", "rs500"),
        assoc(A, "1:300:A:T", "rs300", eaf=0.1),
        assoc(A, "1:400:G:C", "rs400", eaf=0.45),
    ],
    B: [assoc(B, "1:500:C:T", "rs500"), assoc(B, "2:5:A:G", "rs5")],
}
# Proxies of the target, best first by r2: 1:200 (not held), 1:300 (palindrome, maf 0.1),
# 1:400 (palindrome, maf 0.45), 1:500 (negative r).
PROXIES = [
    {"query": "1:100:A:G", "proxy": "1:200:A:G", "r": 0.99, "r2": 0.98, "distance": 100},
    {"query": "1:100:A:G", "proxy": "1:300:A:T", "r": 0.97, "r2": 0.94, "distance": 200},
    {"query": "1:100:A:G", "proxy": "1:400:G:C", "r": 0.95, "r2": 0.90, "distance": 300},
    {"query": "1:100:A:G", "proxy": "1:500:C:T", "r": -0.92, "r2": 0.85, "distance": 400},
]


def answer(endpoint: str, body: dict[str, Any]) -> list[dict[str, Any]]:
    if endpoint == "/api/associations":
        wanted = set(body["variants"])
        return [
            r for a in body["analyses"] for r in HELD.get(a, []) if wanted & {r["alid"], r["rsid"]}
        ]
    if endpoint == "/api/associations/range":
        return [assoc(a, "7:50:A:G", "rs7") for a in body["analyses"]]
    if endpoint == "/api/variants/rsid":
        return [
            {"rsid": r, "alid": {"rs100": "1:100:A:G", "rs101": "1:101:A:G"}.get(r, "1:101:A:G")}
            for r in body["rsids"]
            if r != "rs0"
        ] + ([{"rsid": "rs100", "alid": "1:100:A:C"}] if "rs100" in body["rsids"] else [])
    if endpoint == "/api/variants/chrpos":
        return [{"alid": "1:100:A:G", "rsid": "rs100"}] if body["positions"] == ["1:100"] else []
    if endpoint == "/api/ld/proxies":
        return [p for p in PROXIES if p["query"] in body["alids"]]
    return []


INFO = {
    A: {"id": A, "assigned_ancestry": "EUR", "sample_size": 10},
    B: {"id": B, "assigned_ancestry": "MID", "sample_size": 20},
}


def gwasinfo(request: httpx.Request) -> httpx.Response:
    ids = json.loads(request.content)["id"]
    return httpx.Response(200, json={"analyses": [INFO[i] for i in ids if i in INFO]})


def serve() -> JobServer:
    respx.post(f"{BASE}/api/gwasinfo").mock(side_effect=gwasinfo)
    respx.get(f"{BASE}/api/ld/stores").respond(
        json={"stores": [{"ancestry": "EUR", "store": "eur"}]}
    )
    return JobServer(BASE, answer)


@respx.mock
def test_best_usable_proxy_aligned_to_target() -> None:
    server = serve()
    with pytest.warns(UserWarning, match="no LD store for ancestry MID"):
        frame = compat.associations(["1:100:A:G"], [A, B])
    by_id = {r["id"]: r for r in frame.to_dict("records")}
    # A: 1:200 not held; 1:300 palindromic with maf 0.1 < 0.3, so usable.
    a = by_id[A]
    assert (a["proxy"], a["proxy_snp"], a["proxy_r2"]) == (True, "rs300", 0.94)
    assert (a["ea"], a["nea"]) == ("A", "G")  # r > 0, effect allele = proxy's first: target's first
    assert (a["target_a1"], a["target_a2"], a["proxy_a1"], a["proxy_a2"]) == ("A", "G", "A", "T")
    # B: only 1:500 held; r < 0 so its first allele C tags the target's second allele G.
    b = by_id[B]
    assert (b["proxy_snp"], b["ea"], b["nea"], b["n"]) == ("rs500", "G", "A", 20)
    assert {e for e, _ in server.bodies} >= {"/api/associations", "/api/ld/proxies"}
    proxies_bodies = [b for e, b in server.bodies if e == "/api/ld/proxies"]
    assert proxies_bodies == [{"ancestry": "EUR", "alids": ["1:100:A:G"], "r2": 0.8, "kb": 10_000}]


@respx.mock
def test_palindrome_rules() -> None:
    serve()
    none = compat.associations(["1:100:A:G"], [A], palindromes=0)
    assert none.iloc[0]["proxy_snp"] == "rs500"
    strict = compat.associations(["1:100:A:G"], [A], maf_threshold=0.05)
    assert strict.iloc[0]["proxy_snp"] == "rs500"


@respx.mock
def test_unaligned_keeps_proxy_alleles() -> None:
    serve()
    frame = compat.associations("1:100:A:G", A, align_alleles=0, palindromes=0)
    row = frame.iloc[0]
    assert (row["ea"], row["nea"], row["target_snp"]) == ("C", "T", "1:100:A:G")


@respx.mock
def test_direct_rows_and_no_proxies() -> None:
    server = serve()
    frame = compat.associations(["rs500", "1:100:A:G"], [A], proxies=0)
    assert list(frame["rsid"]) == ["rs500"] and frame["proxy"].tolist() == [False]
    assert all(e != "/api/ld/proxies" for e, _ in server.bodies)


@respx.mock
def test_rsid_targets_positions_and_ranges() -> None:
    serve()
    with (
        pytest.warns(UserWarning, match="rs100 has 2 variants; proxies are for 1:100:A:G"),
        pytest.warns(UserWarning, match="no variant is held at 9:9"),
    ):
        frame = compat.associations(["rs100", "rs0", "1:100", "7:40-60", "9:9"], [A])
    assert set(frame["rsid"]) >= {"rs7", "rs300"}
    targets = set(frame.loc[frame["proxy"], "target_snp"])
    assert targets == {"rs100", "1:100:A:G"}


@respx.mock
def test_nothing_found() -> None:
    respx.post(f"{BASE}/api/gwasinfo").respond(
        json={"analyses": [{"id": A, "analysis_id": "A", "assigned_ancestry": "EUR"}]}
    )
    respx.get(f"{BASE}/api/ld/stores").respond(
        json={"stores": [{"ancestry": "EUR", "store": "eur"}]}
    )
    JobServer(BASE, lambda e, b: [])
    with pytest.warns(UserWarning, match="no variant is held at 9:9"):
        assert compat.associations(["9:9"], [A]).empty
    assert compat.associations(["rs1"], [A]).empty


@respx.mock
def test_no_candidates_for_an_ancestry() -> None:
    respx.post(f"{BASE}/api/gwasinfo").respond(
        json={"analyses": [{"id": A, "assigned_ancestry": "EUR"}]}
    )
    respx.get(f"{BASE}/api/ld/stores").respond(
        json={"stores": [{"ancestry": "EUR", "store": "eur"}]}
    )
    JobServer(BASE, lambda e, b: [{"rsid": "rs9", "alid": "1:9:A:G"}] if e.endswith("rsid") else [])
    assert compat.associations(["rs9"], [A]).empty


@respx.mock
def test_found_directly_in_one_analysis_proxied_in_other() -> None:
    serve()
    with pytest.warns(UserWarning, match="MID"):
        frame = compat.associations(["rs500", "rs5"], [A, B])
    direct = frame[~frame["proxy"]]
    assert sorted(zip(direct["id"], direct["rsid"], strict=True)) == [
        (A, "rs500"),
        (B, "rs5"),
        (B, "rs500"),
    ]
    # rs5 is missing from A, but has no ALID in this fake (lookup gives 1:101), and no proxies.
    assert frame["proxy"].sum() == 0


@respx.mock
def test_palindromic_proxy_without_eaf_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        HELD, A, [{**assoc(A, "1:300:A:T", "rs300"), "eaf": None}, assoc(A, "1:500:C:T", "rs500")]
    )
    serve()
    frame = compat.associations(["1:100:A:G"], [A])
    assert frame.iloc[0]["proxy_snp"] == "rs500"


@respx.mock
def test_missing_targets_without_alids_are_skipped() -> None:
    serve()
    with pytest.warns(UserWarning, match="MID"):
        frame = compat.associations(["rs0"], [A, B])
    assert frame.empty
