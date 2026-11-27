"""The Local Source, on ogquery's contract releases (tests/data/ogquery-contract)."""

import json
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("ogquery")

import opengwaspy as og
from opengwaspy.errors import RequestError
from opengwaspy.local import LocalExtraMissing, LocalSource, LocalUnsupported
from opengwaspy.local._source import LocalSourceError, _ogquery

CONTRACT = Path(__file__).parent / "data" / "ogquery-contract"


def release(tmp_path: Path, name: str, store_id: str, **manifest: Any) -> Path:
    """A copy of a contract release, under its own Store ID."""
    target = tmp_path / f"{store_id}-{name}"
    shutil.copytree(CONTRACT / name, target)
    path = target / "manifest.json"
    data = json.loads(path.read_text())
    data.update(store_id=store_id, **manifest)
    path.write_text(json.dumps(data))
    return target


@pytest.fixture
def two(tmp_path: Path) -> Iterator[LocalSource]:
    """Dense OGS-D (bmi_irn) and Ragged OGS-R (trait_a)."""
    source = og.local(
        [release(tmp_path, "dense_ranges", "OGS-D"), release(tmp_path, "ragged_ranges", "OGS-R")]
    )
    yield source
    source.close()


def test_open(two: LocalSource) -> None:
    assert two.served_releases() == {"OGS-D": ["r"], "OGS-R": ["r"]}
    assert [r.layout for r in two.releases] == ["dense", "ragged"]
    assert all(r.format_version == "0.3.0" for r in two.releases)
    assert repr(two) == "LocalSource(OGS-D/r, OGS-R/r)"
    assert two.limits.lookup_variants >= 10**9 and two.image_digest is None
    assert two.is_local


def test_associations_by_rsid_and_alid(two: LocalSource) -> None:
    frame = og.associations(["rs5000", "2:2000:G:T"], ["OGS-R:trait_a"], client=two)
    assert list(frame["alid"]) == ["1:5000:A:C", "1:5000:C:G"]  # rs5000 is multi-allelic
    assert set(frame["store_id"]) == {"OGS-R"} and set(frame["release_id"]) == {"r"}
    assert list(frame.columns[-2:]) == ["store_id", "release_id"]
    assert frame["p"].iloc[0] == pytest.approx(10 ** frame["log10_p"].iloc[0])
    assert frame.attrs["source"] == "local" and frame.attrs["job_id"] is None
    assert frame.attrs["releases"] == [{"store_id": "OGS-R", "release_id": "r"}]
    assert frame.attrs["ogquery_version"].startswith("0.")


def test_non_finite_statistics_are_missing_as_from_the_api(two: LocalSource) -> None:
    frame = og.associations("1:1000:A:G", "bmi_irn", client=two)  # an infinite SE
    row = frame.iloc[0]
    assert row["z"] == -6.0
    for column in ("se", "beta", "pval", "log10_p", "p"):
        assert row[column] is None or row[column] != row[column]  # None or NaN


def test_range_in_genome_order_across_stores(two: LocalSource) -> None:
    frame = og.associations_range("1", 1, 10_000_000, client=two)
    assert list(frame["store_id"]) == sorted(frame["store_id"])
    dense = frame[frame["store_id"] == "OGS-D"]
    assert list(dense["position"]) == sorted(dense["position"])
    assert set(frame["chromosome"]) == {"1"}
    only = og.associations_range("1", 1, 10_000_000, ["trait_a"], client=two)
    assert set(only["analysis_id"]) == {"trait_a"}
    assert len(only) == (frame["analysis_id"] == "trait_a").sum()


def test_range_matches_the_reader(two: LocalSource) -> None:
    frame = og.associations_range("X", 1, 10**9, ["OGS-D:bmi_irn"], client=two)
    query = two.releases[0].query
    raw = query.range_phewas("X", 1, 10**9, observed_only=True)
    expected = list(query.resolve(raw, include_variant_info=True))
    assert list(frame["alid"]) == [row["alid"] for row in expected]
    assert list(frame["z"]) == [row["z"] for row in expected]


def test_whole_analysis(two: LocalSource) -> None:
    frame = og.associations_analysis("OGS-D:bmi_irn", client=two)
    chromosomes = list(dict.fromkeys(frame["chromosome"]))
    assert chromosomes == ["1", "2", "X"]
    assert set(frame["analysis_id"]) == {"bmi_irn"}


def test_releases_filter(two: LocalSource) -> None:
    frame = og.associations_range("1", 1, 10_000_000, releases=["OGS-R"], client=two)
    assert set(frame["store_id"]) == {"OGS-R"}
    with pytest.raises(RequestError) as caught:
        og.associations_range("1", 1, 10, releases=["OGS-R/other"], client=two)
    assert caught.value.error == "release_not_found"


def test_analysis_naming(tmp_path: Path) -> None:
    with og.local(
        [release(tmp_path, "dense_ranges", "OGS-1"), release(tmp_path, "hybrid_ranges", "OGS-2")]
    ) as source:
        with pytest.raises(RequestError, match="OGS-1:bmi_irn, OGS-2:bmi_irn") as caught:
            og.associations("rs5000", "bmi_irn", client=source)
        assert caught.value.error == "ambiguous_analysis"
        hybrid = og.associations("rs5000", "OGS-2:bmi_irn", client=source)
        assert set(hybrid["store_id"]) == {"OGS-2"} and len(hybrid) == 2
        for missing in ("OGS-3:bmi_irn", "OGS-1:nope", "nope"):
            with pytest.raises(RequestError) as caught:
                og.associations("rs5000", missing, client=source)
            assert caught.value.error == "analysis_not_found"
        with pytest.raises(RequestError, match="not translated locally"):
            og.associations("rs5000", "ieu-a-2", client=source)


def test_reader_refusals(two: LocalSource) -> None:
    with pytest.raises(RequestError) as caught:
        og.associations_range("27", 1, 10, client=two)
    assert caught.value.error == "invalid_query" and "27" in str(caught.value)


def test_unsupported(two: LocalSource) -> None:
    with pytest.raises(LocalUnsupported, match="api/tophits"):
        two.query("api/tophits", {"analyses": ["bmi_irn"]})
    with pytest.raises(LocalUnsupported, match=r"opengwaspy\.gwasinfo"):
        og.gwasinfo(["bmi_irn"], client=two)  # type: ignore[arg-type]
    with pytest.raises(LocalUnsupported, match=r"opengwaspy\.ld_stores"):
        og.ld_stores(client=two)  # type: ignore[arg-type]
    with pytest.raises(LocalUnsupported, match=r"opengwaspy\.status"):
        og.status(client=two)  # type: ignore[arg-type]


def test_one_release_per_store(tmp_path: Path) -> None:
    with pytest.raises(LocalSourceError, match="two releases of Store s"):
        og.local([CONTRACT / "dense_ranges", CONTRACT / "ragged_ranges"])


def test_refused_paths(tmp_path: Path) -> None:
    with pytest.raises(LocalSourceError, match="no Store Release"):
        og.local(tmp_path / "missing")
    with pytest.raises(LocalSourceError, match="cannot be opened"):
        og.local(tmp_path)
    old = release(tmp_path, "dense_ranges", "OGS-1", format_version="0.2.3")
    with pytest.raises(LocalSourceError, match="ogdb rewrite-release"):
        og.local(old)
    older = release(tmp_path, "ragged_ranges", "OGS-2", format_version="0.1.0")
    with pytest.raises(LocalSourceError, match="rebuild"):
        og.local([older])
    with pytest.raises(ValueError, match="paths is empty"):
        og.local([])


def test_query_many_in_order(two: LocalSource) -> None:
    frames = two.query_many(
        [
            ("api/associations", {"variants": ["rs5000"], "analyses": ["trait_a"]}),
            ("api/associations", {"variants": ["rs1000"], "analyses": ["bmi_irn"]}),
        ]
    )
    assert [set(f["store_id"]) for f in frames] == [{"OGS-R"}, {"OGS-D"}]


def test_whole_analysis_needs_analyses(two: LocalSource) -> None:
    with pytest.raises(RequestError, match="analyses is required"):
        two.query("api/associations/analysis", {})


def test_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    def refuse(name: str) -> Any:
        raise ImportError(name)

    monkeypatch.setattr(importlib, "import_module", refuse)
    with pytest.raises(LocalExtraMissing, match=r'pip install "opengwaspy\[local\]"'):
        _ogquery()
    monkeypatch.setattr(sys, "version_info", (3, 10, 0))
    with pytest.raises(LocalExtraMissing, match=r"Python 3.12 or later \(this is 3.10\)"):
        _ogquery()


def test_row_order_and_error_mapping() -> None:
    from ogquery.analyses import UnknownAnalysisError

    from opengwaspy.local._source import _row_key, _translated

    rows: list[dict[str, Any]] = [
        {"store_id": "S", "analysis_id": "a", "chromosome": "", "position": None, "alid": "z"},
        {"store_id": "S", "analysis_id": "a", "chromosome": "X", "position": 5, "alid": "x"},
        {"store_id": "S", "analysis_id": "a", "chromosome": "10", "position": 9, "alid": "b"},
        {"store_id": "S", "analysis_id": "a", "chromosome": "2", "position": 100, "alid": "a"},
    ]
    assert [r["alid"] for r in sorted(rows, key=_row_key)] == ["a", "b", "x", "z"]

    def unknown() -> list[dict[str, Any]]:
        raise UnknownAnalysisError("q")

    with pytest.raises(RequestError) as caught:
        _translated(unknown)
    assert caught.value.error == "analysis_not_found"
