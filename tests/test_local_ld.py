"""LD from downloaded LD Stores and Genotype Stores (tests/data/ogquery-ld)."""

import json
import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ogquery.ld")

import opengwaspy as og
from opengwaspy.errors import LDRefusal, RequestError
from opengwaspy.local import LocalLDError, LocalSource

PANEL = Path(__file__).parent / "data" / "ogquery-ld" / "test-panel"
CONTRACT = Path(__file__).parent / "data" / "ogquery-contract"


def genotype_store(tmp_path: Path) -> Path:
    """A copy of the Test Panel's Genotype Store, its pgen files at their pinned mtimes."""
    panel = tmp_path / "panel"
    shutil.copytree(PANEL, panel)
    store = panel / "genotype-store"
    attributes = json.loads((store / "zarr.json").read_text())["attributes"]["genotype_store"]
    for fileset in attributes["filesets"]:
        for name in ("pgen", "psam", "pvar"):
            pin = fileset[name]
            os.utime(store / pin["path"], ns=(pin["mtime_ns"], pin["mtime_ns"]))
    return store


@pytest.fixture
def source() -> Iterator[LocalSource]:
    with og.local(ld=[PANEL / "store"]) as opened:
        yield opened


def first(source: LocalSource, n: int) -> list[str]:
    store = source.ld_stores[0].store
    return [str(a) for a in store.variants_in("22", 0, 10**9).alid[:n]]


def test_ld_stores_listing(source: LocalSource) -> None:
    frame = og.ld_stores(client=source)
    row = frame.iloc[0]
    assert (row["store"], row["ancestry"], row["kind"]) == ("store", "EUR", "ld_store")
    assert row["near_bp"] == 3_000_000 and row["t_partner"] == pytest.approx(0.01)
    assert repr(source) == "LocalSource(LD store)"


def test_ld_matrix_equals_the_reader(source: LocalSource) -> None:
    alids = [*first(source, 3), "22:1:A:C"]
    square = og.ld_matrix(alids, ancestry="EUR", client=source)
    direct = source.ld_stores[0].store.matrix(alids)
    assert list(square.index) == [str(a) for a in direct.variants.alid]
    np.testing.assert_allclose(square.to_numpy(), direct.r, equal_nan=True)
    assert square.attrs["absent"] == ["22:1:A:C"]
    assert square.attrs["store"] == "store" and square.attrs["ancestry"] == "EUR"


def test_ld_region(source: LocalSource) -> None:
    alid = first(source, 1)[0]
    chromosome, position = alid.split(":")[:2]
    square = og.ld_region(chromosome, int(position), 50_000, store="store", client=source)
    assert alid in square.index and square.shape[0] == square.shape[1]


def test_ld_proxies_clump_and_reflookup(source: LocalSource) -> None:
    alids = first(source, 30)
    proxies = og.ld_proxies(alids[:2], r2=0.2, kb=500, ancestry="EUR", client=source)
    assert set(proxies.columns) >= {"query", "proxy", "r", "r2", "distance"}
    assert (proxies["r2"] >= 0.2).all()
    clumps = og.ld_clump(
        alids, list(range(30, 0, -1)), r2=0.1, kb=1000, ancestry="EUR", client=source
    )
    assert clumps["lead"].iloc[0] == alids[0]
    assert clumps.attrs["metadata"]["leads"] == (clumps["alid"] == clumps["lead"]).sum()
    found = og.ld_reflookup([alids[0], "22:1:A:C"], ancestry="EUR", client=source)
    assert list(found["present"]) == [True, False]


def test_refusals_pass_through(source: LocalSource) -> None:
    with pytest.raises(LDRefusal) as caught:
        og.ld_proxies(first(source, 1), r2=0.0001, kb=10_000, ancestry="EUR", client=source)
    assert caught.value.reason == "threshold_below_t_far"
    assert caught.value.near_bp == 3_000_000 and "This store answers" in str(caught.value)


def test_choosing_a_store(tmp_path: Path) -> None:
    other = tmp_path / "eur-copy.store"
    shutil.copytree(PANEL / "store", other)
    with og.local(ld=[PANEL / "store", other]) as two:
        assert [s.name for s in two.ld_stores] == ["store", "eur-copy"]
        assert not og.ld_reflookup("22:1:A:C", store="eur-copy", client=two)["present"].any()
        with pytest.raises(RequestError, match="name one with store=") as caught:
            og.ld_reflookup("22:1:A:C", ancestry="EUR", client=two)
        assert caught.value.error == "ambiguous_ld_store"
        with pytest.raises(RequestError) as missing:
            og.ld_reflookup("22:1:A:C", ancestry="AFR", client=two)
        assert missing.value.error == "ld_store_not_found"
        with pytest.raises(RequestError) as named:
            og.ld_reflookup("22:1:A:C", store="nope", client=two)
        assert named.value.error == "ld_store_not_found"


@pytest.mark.skipif(os.name == "nt", reason="pgenlib has no Windows wheels")
def test_genotype_store_answers_as_the_ld_store(tmp_path: Path) -> None:
    pytest.importorskip("pgenlib")
    with og.local(ld=[PANEL / "store", genotype_store(tmp_path)]) as two:
        listing = og.ld_stores(client=two).set_index("store")
        assert listing.loc["genotype-store", "kind"] == "genotype_store"
        alids = first(two, 5)
        stored = og.ld_matrix(alids, store="store", client=two)
        computed = og.ld_matrix(alids, store="genotype-store", client=two)
        np.testing.assert_allclose(
            stored.to_numpy(), computed.to_numpy(), atol=0.02, equal_nan=True
        )


def test_genotype_store_with_changed_files_is_refused(tmp_path: Path) -> None:
    store = genotype_store(tmp_path)
    pgen = store.parent / "panel.pgen"
    os.utime(pgen, ns=(1, 1))
    with pytest.raises(LocalLDError, match=r"keeping their times|genotype extra"):
        og.local(ld=[store])


def test_bad_ld_paths(tmp_path: Path) -> None:
    with pytest.raises(LocalLDError, match="no LD Store"):
        og.local(ld=[tmp_path / "missing"])
    with pytest.raises(LocalLDError, match="cannot be opened"):
        og.local(ld=[tmp_path])
    copy = tmp_path / "x" / "store"
    shutil.copytree(PANEL / "store", copy)
    with pytest.raises(LocalLDError, match="two LD Stores are named store"):
        og.local(ld=[PANEL / "store", copy])
    with pytest.raises(ValueError, match="paths is empty"):
        og.local()


def test_releases_and_ld_together(tmp_path: Path) -> None:
    with og.local(CONTRACT / "dense_ranges", ld=PANEL / "store") as both:
        assert len(both.releases) == 1 and len(both.ld_stores) == 1
        assert not og.associations_range("1", 1, 10_000, client=both).empty
