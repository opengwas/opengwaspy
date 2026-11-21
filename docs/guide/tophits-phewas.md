# Top hits and PheWAS

## Top hits

`tophits` returns each analysis's associations at or below a p-value threshold, strongest first:

```python
import opengwaspy as og

t = og.tophits("OGS-00006:GCST90199621", limit=3)
t[["analysis_id", "rsid", "alid", "z", "p"]]
```

```text
 analysis_id      rsid            alid          z             p
GCST90199621 rs1171617 10:59707424:G:T -24.639648 4.751576e-134
GCST90199621 rs1171614 10:59709780:C:T  24.575195 2.326877e-133
GCST90199621 rs1171615 10:59709332:C:T -24.568359 2.753232e-133
```

```text
UserWarning: some analyses have more than 3 hits at p <= 5e-08; only the strongest were returned (raise limit for more)
```

!!! warning "Not clumped"
    These three hits are one signal: neighbouring variants in LD. The Data API does not
    LD-clump top hits. ieugwaspy's `tophits` clumped by default; the ieugwaspy-compatible
    layer will do so through the LD operations, and [`ld_clump`](ld.md#clumping) lets you
    clump them yourself.

- **`threshold`** (default 5e-8) is exact. Each Store's index holds tiers up to 5e-4. A looser threshold raises `RequestError` with code `unsupported_threshold`, and `error.extra["indexed_thresholds"]` lists the tiers, for example `[5e-08, 5e-06, 0.0005]`.
- **`limit`** (default 1,000) is per analysis, keeping the largest |z|. `attrs["truncated"]` says whether any analysis was cut, and opengwaspy warns when it was.
- **`observed_only`** defaults to `False` for top hits, as in the API.

## PheWAS

`phewas` returns the associations of one variant across analyses, at p ≤ `threshold` (1e-8 by default, the Data API's own):

```python
ph = og.phewas("rs1171617")
len(ph), ph.attrs["total"]  # (67, 67)
ph.sort_values("p")[["store_id", "analysis_label", "z", "p"]].head(4)
```

```text
 store_id   analysis_label          z             p
OGS-00006 Carnitine levels -24.639648 4.751576e-134
OGS-00012     GCST90475362  19.163086  7.527510e-82
OGS-00012     GCST90475359  18.823242  4.871065e-79
OGS-00012     GCST90475365  17.239258  1.347557e-66
```

- **The threshold is applied on the server,** before any row is built, so `total`, `limit` and truncation count only the associations that pass it. Pass `threshold=1` for every association: rs1171617 has 10,662, more than the default `limit` returns:

    ```text
    UserWarning: the PheWAS of rs1171617 has 10662 associations at p <= 1; only 1002 were returned (raise limit, up to 10,000 per job, or lower threshold)
    ```

- **Releases.** By default, every served Store that can answer PheWAS is searched, 10 releases per job (13 Stores, two jobs). Pass `releases=` to search fewer.
- `attrs` has `threshold`, `total` (associations that passed it), `returned` and `truncated`.
- One variant per call: an rsID or an ALID.
