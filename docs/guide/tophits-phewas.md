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
    layer will do so through the LD operations, and the LD functions will let you clump
    them yourself.

- **`threshold`** (default 5e-8) is exact. Each Store's index holds tiers up to 5e-4. A looser threshold raises `RequestError` with code `unsupported_threshold`, and `error.extra["indexed_thresholds"]` lists the tiers, for example `[5e-08, 5e-06, 0.0005]`.
- **`limit`** (default 1,000) is per analysis, keeping the largest |z|. `attrs["truncated"]` says whether any analysis was cut, and opengwaspy warns when it was.
- **`observed_only`** defaults to `False` for top hits, as in the API.

## PheWAS

`phewas` returns every association of one variant across analyses:

```python
ph = og.phewas("rs1171617")
ph.sort_values("p")[["store_id", "analysis_label", "z", "p"]].head(4)
```

```text
 store_id                 analysis_label          z             p
OGS-00006               Carnitine levels -24.639648 4.751576e-134
OGS-00006                 X-12798 levels  14.945312  1.671054e-50
OGS-00006 Propionylcarnitine (c3) levels -13.914062  5.203778e-44
OGS-00006    Acetylcarnitine (c2) levels -11.958984  5.827023e-33
```

```text
UserWarning: the PheWAS of rs1171617 has 10662 associations; only 1002 were returned (raise limit for more)
```

- **Releases.** By default, every served Store that can answer PheWAS is searched, 10 releases per job (13 Stores took two jobs and 10 s on 19 Nov 2026). Pass `releases=` to search fewer.
- **No p-value filter on the server.** ieugwaspy's `phewas(pval=...)` filtered on the server; here you filter the table: `ph[ph.p < 1e-5]`. Check `ph.attrs["truncated"]` first: if it is true, rows beyond `limit` were never returned, so a filter cannot see them. Raise `limit`, or narrow `releases` or `analyses`.
- `attrs` has `total` (associations that qualified) and `returned`.
- One variant per call: an rsID or an ALID.
