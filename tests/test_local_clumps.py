"""Clumped top hits on a Local Source: stored Clumps, and clumping on the fly locally."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

pytest.importorskip("ogquery")

import opengwaspy as og
from opengwaspy.errors import LDRefusal, RequestError
from opengwaspy.local import LocalSource
from tests.test_local import release

PANEL = Path(__file__).parent / "data" / "ogquery-ld" / "test-panel" / "store"
#: dense_ranges' 5e-8 tier, in tier order: 1:1000:A:G, 1:5000:A:C, 1:5000:C:G, 1:5000:C:T,
#: 1:9000:A:G, 2:300:C:T, 2:7000:A:C, X:2500:G:T. Leads: 1:5000:C:T (for four), 2:300:C:T
#: (two), X:2500:G:T (itself); 1:9000:A:G is absent from the LD resource (marker -1).
LEADS = [3, 3, 3, 3, -1, 5, 5, 7]
STORED_R2 = 0.0319


def with_stored_clumps(path: Path) -> Path:
    """Write stored Clumps (Store spec §18.1) into a copied release's 5e-8 tier."""
    import ogquery.ld
    import zarr
    from ogquery.top_hits import CLUMPS_ATTRIBUTE_KEYS

    with ogquery.ld.open(str(PANEL), cache_bytes=0) as panel:
        provenance: dict[str, Any] = dict(panel.provenance)
    entry: dict[str, Any] = {
        "name": "store",
        "kind": "ld_store",
        "samples_sha256": provenance["panel"]["samples_sha256"],
        "k": provenance["adjustment"]["k"],
        "r2": STORED_R2,
        "t_far": provenance["t_far"],
        "near_bp": provenance["near_bp"],
        "far_bp": provenance["far_bp"],
    }
    attribute: dict[str, Any] = {key: None for key in CLUMPS_ATTRIBUTE_KEYS}
    attribute.update(
        configuration="default",
        threshold=5e-8,
        tier_rows=len(LEADS),
        score="abs_z",
        kb=10_000,
        ld_stores={"EUR": entry},
        opengwasdb="test",
        created_at="2026-11-27",
    )
    tier = zarr.open_group(str(path / "data.zarr"), path="top_hits/p_5e_08", mode="r+")
    default = tier.create_group("clumps").create_group("default")
    default.create_array("lead", data=np.asarray(LEADS, dtype=np.int32))
    default.create_array("r", data=np.zeros(len(LEADS), dtype=np.int16))
    default.attrs["clumps"] = attribute
    manifest = json.loads((path / "manifest.json").read_text())
    manifest["clumps"] = {"tier": "p_5e_08", "configuration": "default"}
    (path / "manifest.json").write_text(json.dumps(manifest))
    return path


@pytest.fixture
def source(tmp_path: Path) -> Iterator[LocalSource]:
    clumped = with_stored_clumps(release(tmp_path, "dense_ranges", "OGS-C"))
    plain = release(tmp_path, "hybrid_ranges", "OGS-P")
    with og.local([clumped, plain], ld=[PANEL]) as opened:
        yield opened


def test_stored_clumps_by_default(source: LocalSource) -> None:
    leads = og.tophits("OGS-C:bmi_irn", clump=True, client=source)
    assert list(leads["alid"]) == ["1:5000:C:T", "X:2500:G:T", "2:300:C:T"]
    assert list(leads["clump_size"]) == [4, 1, 2]
    assert set(leads["clump_source"]) == {"stored"}
    summary = leads.attrs["clump"]
    assert summary["source"] == "stored" and summary["r2"] is None
    assert (summary["hits"], summary["leads"], summary["absent"]) == (8, 3, 1)
    configuration = summary["stored"]["OGS-C/r"]["configuration"]
    assert configuration["kb"] == 10_000 and configuration["ld_stores"]["EUR"]["r2"] == STORED_R2


def test_stored_clumps_on_an_exact_match_only(source: LocalSource) -> None:
    exact = og.tophits("OGS-C:bmi_irn", clump={"r2": STORED_R2, "kb": 10_000}, client=source)
    assert exact.attrs["clump"]["source"] == "stored"
    other = og.tophits("OGS-C:bmi_irn", clump={"r2": 0.1, "kb": 1000}, client=source)
    assert other.attrs["clump"]["source"] == "computed"
    assert other.empty and other.attrs["clump"]["absent"] == 8  # chr22's panel holds none of them
    assert other.attrs["clump"]["ld_stores"] == {"EUR": "store"}
    another_threshold = og.tophits(
        "OGS-C:bmi_irn", threshold=1e-10, clump={"r2": 0.1, "kb": 1000}, client=source
    )
    assert another_threshold.attrs["clump"]["source"] == "computed"


def test_named_store_matching_the_stored_panel(source: LocalSource) -> None:
    leads = og.tophits("OGS-C:bmi_irn", clump={"store": "store"}, client=source)
    assert leads.attrs["clump"]["source"] == "stored"


def test_computed_refusal_passes_through(source: LocalSource) -> None:
    # The Hybrid has no stored Clumps: clumped on the fly at r² 0.001 within 3,000 kb, which the
    # Test Panel refuses below its t_partner (0.01) rather than answering approximately.
    with pytest.raises(LDRefusal) as caught:
        og.tophits("OGS-P:bmi_irn", clump=True, client=source)
    assert caught.value.reason == "threshold_below_t_partner"


def test_computed_needs_an_open_ld_store(tmp_path: Path) -> None:
    with og.local(release(tmp_path, "dense_ranges", "OGS-D")) as no_ld:
        with pytest.raises(RequestError, match="no LD Store is open for EUR") as caught:
            og.tophits("OGS-D:bmi_irn", clump=True, client=no_ld)
        assert caught.value.error == "ld_store_not_found"


def test_clump_needs_analyses(source: LocalSource) -> None:
    with pytest.raises(RequestError, match="analyses is required"):
        source.query("api/tophits", {"clump": {}})


def test_the_owners_rule() -> None:
    from types import SimpleNamespace

    from opengwaspy.local._clumps import _answers

    facts: dict[str, Any] = {
        "threshold": 5e-8,
        "kb": 10_000,
        "ld_stores": {"EUR": {"r2": STORED_R2, "samples_sha256": "s", "k": 10}},
    }
    eur = SimpleNamespace(
        ancestry="EUR", provenance={"panel": {"samples_sha256": "s"}, "adjustment": {"k": 10}}
    )
    other = SimpleNamespace(
        ancestry="EUR", provenance={"panel": {"samples_sha256": "t"}, "adjustment": {"k": 10}}
    )
    other_k = SimpleNamespace(
        ancestry="EUR", provenance={"panel": {"samples_sha256": "s"}, "adjustment": {"k": 15}}
    )
    afr = SimpleNamespace(ancestry="AFR", provenance={"panel": {}, "adjustment": {}})

    def decide(
        clump: dict[str, Any],
        *,
        threshold: float = 5e-8,
        named: Any = None,
        ancestries: frozenset[str] = frozenset({"EUR"}),
        given: Any = facts,
    ) -> bool:
        r2 = float(clump.get("r2", 0.001))
        kb = float(clump.get("kb", 3000))
        return _answers(given, clump, r2, kb, threshold, set(ancestries), named)

    assert decide({})
    assert not decide({}, given=None)
    assert not decide({}, threshold=1e-10)
    assert decide({}, named=eur)
    assert not decide({}, named=other)
    assert not decide({}, named=other_k)
    assert not decide({}, named=afr)
    assert decide({"r2": STORED_R2, "kb": 10_000})
    assert not decide({"r2": STORED_R2})  # an explicit r2 keeps the default window
    assert not decide({"kb": 10_000})  # and an explicit kb the default r2
    assert not decide({"r2": 0.1, "kb": 10_000})
    assert not decide({"r2": STORED_R2, "kb": 10_000}, ancestries=frozenset({"AFR"}))


def test_undeclared_clumps_are_not_read(tmp_path: Path) -> None:
    path = with_stored_clumps(release(tmp_path, "dense_ranges", "OGS-U"))
    manifest = json.loads((path / "manifest.json").read_text())
    del manifest[
        "clumps"
    ]  # a group the manifest does not declare: left by a step that never finished
    (path / "manifest.json").write_text(json.dumps(manifest))
    with og.local(path, ld=[PANEL]) as source:
        frame = og.tophits("OGS-U:bmi_irn", clump={"r2": 0.1, "kb": 1000}, client=source)
        assert frame.attrs["clump"]["source"] == "computed"
        from opengwaspy.local._clumps import stored_facts

        assert stored_facts(source.releases[0]) is None


def test_several_stores_of_the_ancestry(tmp_path: Path) -> None:
    import shutil

    copy = tmp_path / "eur2.store"
    shutil.copytree(PANEL, copy)
    with og.local(release(tmp_path, "dense_ranges", "OGS-D"), ld=[PANEL, copy]) as source:
        with pytest.raises(RequestError, match="name one in clump") as caught:
            og.tophits("OGS-D:bmi_irn", clump={"r2": 0.1, "kb": 1000}, client=source)
        assert caught.value.error == "ambiguous_ld_store"
        named = og.tophits(
            "OGS-D:bmi_irn", clump={"r2": 0.1, "kb": 1000, "store": "eur2"}, client=source
        )
        assert named.attrs["clump"]["ld_stores"] == {"EUR": "eur2"}
