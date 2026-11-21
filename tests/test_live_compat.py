"""Live checks of the ieugwaspy-compatible layer, through the default client."""

from collections.abc import Iterator

import pytest

import opengwaspy as og
import opengwaspy.compat as compat
from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def default_client(live_api: LiveAPI) -> Iterator[None]:
    client = og.configure(url=live_api.url, token=live_api.token)
    yield
    client.close()


def test_gwasinfo(capsys: pytest.CaptureFixture[str]) -> None:
    frame = compat.gwasinfo(["OGS-00006:GCST90199621", "ieu-a-2"])
    assert list(frame["trait"]) == ["Carnitine levels"]
    assert "ieu-a-2" in capsys.readouterr().out


def test_tophits_default_refused_then_answerable_clumping() -> None:
    with pytest.raises(og.UnsupportedOptionError, match="kb=3000"):
        compat.tophits("OGS-00006:GCST90199621")
    leads = compat.tophits("OGS-00006:GCST90199621", r2=0.001, kb=3000)
    hits = og.tophits("OGS-00006:GCST90199621")
    assert 0 < len(leads) < len(hits)
    assert "rs1171617" in set(leads["rsid"])
    assert leads.iloc[0]["n"] == 8192


def test_phewas_and_variant_helpers() -> None:
    assert compat.variants_chrpos("10:59707424") == "rs1171617"
    assert compat.variants_to_rsid(["rs1", "19:44908684"]) == ["rs1", "rs429358"]
    frame = compat.phewas("10:59707424", pval=1e-20, batch=["OGS-00006"])
    assert len(frame) > 0 and (frame["p"] <= 1e-20).all()
    assert {"id", "trait", "beta", "n"} <= set(frame.columns) or {"id", "beta", "n"} <= set(
        frame.columns
    )


def test_associations_with_an_aligned_proxy() -> None:
    target = "10:59699398:T:TTAC"  # held by the EUR LD store, not by this analysis
    frame = compat.associations([target, "rs1171617"], ["OGS-00006:GCST90199621"], r2=0.5)
    proxy = frame[frame["proxy"]].iloc[0]
    assert proxy["target_snp"] == target and proxy["proxy_r2"] >= 0.5
    assert {proxy["ea"], proxy["nea"]} == {"T", "TTAC"}
    # The lead G lowers carnitine; the target T is in positive LD with G, so TTAC raises it.
    assert (proxy["ea"] == "TTAC") == (proxy["beta"] > 0)
    assert not frame[~frame["proxy"]].empty


def test_phewas_pval_is_applied_on_the_server() -> None:
    frame = compat.phewas("rs429358", pval=1e-8)
    assert frame.attrs["threshold"] == 1e-8
    assert len(frame) > 100 and (frame["p"] <= 1e-8).all()


def test_opengwas_ids_and_batches_translated(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.warns(UserWarning, match="finn-b-E4_OBESITY -> OGS-00017:"):
        info = compat.gwasinfo(["ebi-a-GCST006802", "finn-b-E4_OBESITY", "ieu-a-2"])
    assert list(info["opengwas_id"]) == ["ebi-a-GCST006802", "finn-b-E4_OBESITY"]
    assert info.iloc[0]["id"] == "OGS-00011:GCST006802"
    matches = {e["id"]: e.get("match", e.get("reason")) for e in info.attrs["opengwas_ids"]}
    assert matches["ebi-a-GCST006802"] == "exact" and matches["finn-b-E4_OBESITY"] == "successor"
    assert "ieu-a-2" in capsys.readouterr().out
    assoc = compat.associations(["rs1421085"], ["ebi-a-GCST006802"])
    assert list(assoc["opengwas_id"]) == ["ebi-a-GCST006802"]
    frame = compat.phewas("rs1421085", pval=1e-8, batch=["ukb-b"])
    assert set(frame["store_id"]) == {"OGS-00009"}
