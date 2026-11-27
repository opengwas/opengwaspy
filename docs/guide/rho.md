# Rho Matrix

A GWAS Store's **Rho Matrix** holds, for each pair of its analyses, the correlation of their null z-scores: phenotypic correlation times sample overlap. Methods that combine analyses, such as multi-trait or meta-analysis methods that correct for overlapping samples, need it.

It was estimated when the Store was built, from its Dense grid. Dense Stores, and Hybrid Stores' Dense Components, carry one. A Ragged Store has none, and is refused with `RequestError` (`rho_unavailable`).

```python
import opengwaspy as og

rho = og.rho(
    "OGS-00017",
    [
        "finngen-r13-AB1_ACTINOMYCOSIS",
        "finngen-r13-AB1_ACTINOMYCOSIS_WIDE",
        "finngen-r13-K11_APPENDACUT",
    ],
)
rho  # a square DataFrame, indexed and labelled by analysis ID
rho.attrs["n_null"]  # the shared null variants behind each pair
rho.attrs["settings"]  # method, z_thresh, min_nulls, grid_n, window_bp, n_variants_used
```

- **One Store Release:** give a Store ID (the release the API serves), `"store_id/release_id"`, or a mapping. A Store with several served releases must be named with its release.
- **Which analyses:** every analysis the matrix holds by default, in the Store's order, or the sub-matrix of `analyses`, rows and columns in the order you give. IDs may be bare or `store_id:analysis_id`.
- **Values:** the diagonal is 1. A pair with fewer than `min_nulls` shared null variants has no Rho: it is NaN, and `n_null` says how many there were. Rho is a `float32` matrix, as the API stores it.
- **Size:** a full matrix is large. OGS-00017's 2,754 analyses are 132 MB from the API, about 30 s to read; in memory it is about 30 MB as `float32`, plus `n_null`. The API counts an unread result against your share of its results cache (256 MB by default), so ask for `analyses` when you need only some.
- **Locally:** pass a Local Source (`client=og.local([...])`) to read the matrix from a downloaded release, with the same frame (see [Downloaded Stores](local.md)).
