"""The Rho Matrix on a Local Source (ogquery's dense_rho and hybrid_overflow_only releases)."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("ogquery")

import opengwaspy as og
from opengwaspy.errors import RequestError
from opengwaspy.local import LocalSource
from tests.test_local import release

CONTRACT = Path(__file__).parent / "data" / "ogquery-contract"


@pytest.fixture
def source(tmp_path: Path) -> Iterator[LocalSource]:
    with og.local(
        [
            release(tmp_path, "dense_rho", "OGS-D"),
            release(tmp_path, "hybrid_overflow_only", "OGS-H"),
            release(tmp_path, "ragged_ranges", "OGS-R"),
        ]
    ) as opened:
        yield opened


def test_full_matrix(source: LocalSource) -> None:
    matrix = og.rho("OGS-D", client=source)
    assert list(matrix.index) == ["trait_a", "trait_b", "trait_c", "trait_d"]
    assert list(matrix.columns) == list(matrix.index)
    assert matrix.dtypes.unique().tolist() == [np.dtype("float32")]
    values = matrix.to_numpy()
    assert values[0, 1] == pytest.approx(0.617, abs=1e-3) and values[1, 0] == values[0, 1]
    assert np.isnan(values[2, 3]) and (np.diag(values) == 1).all()
    assert matrix.attrs["n_null"].shape == (4, 4)
    assert matrix.attrs["settings"]["method"] == "pleiodb-cml"
    assert matrix.attrs["source"] == "local" and matrix.attrs["store_id"] == "OGS-D"


def test_sub_matrix_in_order(source: LocalSource) -> None:
    matrix = og.rho("OGS-D", ["OGS-D:trait_b", "trait_a"], client=source)
    assert list(matrix.index) == ["trait_b", "trait_a"]
    full = og.rho("OGS-D", client=source)
    assert matrix.to_numpy()[0, 1] == full.to_numpy()[1, 0]


def test_hybrid(source: LocalSource) -> None:
    matrix = og.rho("OGS-H", client=source)
    assert list(matrix.index) == ["trait_a", "trait_b", "trait_d"]  # trait_c is Overflow-only
    with pytest.raises(RequestError, match="has no Rho") as caught:
        og.rho("OGS-H", ["trait_c"], client=source)
    assert caught.value.error == "rho_unavailable"


def test_refusals(source: LocalSource) -> None:
    with pytest.raises(RequestError, match="holds no Rho Matrix") as caught:
        og.rho("OGS-R", client=source)
    assert caught.value.error == "rho_unavailable"
    with pytest.raises(RequestError) as unknown:
        og.rho("OGS-D", ["nope"], client=source)
    assert unknown.value.error == "analysis_not_found"
