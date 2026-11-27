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

!!! warning "Not clumped by default"
    These three hits are one signal: neighbouring variants in LD. Pass `clump` to
    clump them on the server (below).

- **`threshold`** (default 5e-8) is exact. Each Store's index holds tiers up to 5e-4. A looser threshold raises `RequestError` with code `unsupported_threshold`, and `error.extra["indexed_thresholds"]` lists the tiers, for example `[5e-08, 5e-06, 0.0005]`.
- **`limit`** (default 1,000) is per analysis, keeping the largest |z|. `attrs["truncated"]` says whether any analysis was cut, and opengwaspy warns when it was.
- **`observed_only`** defaults to `False` for top hits, as in the API.

### Clumped on the server

With `clump`, the Data API clumps **every** hit of each analysis at the threshold, and returns only the leads, strongest first, each with `clump_size` (the hits in its clump) and `clump_source`. The clumps come from one of two places:

| Request | A release with stored Clumps | A release without |
|---|---|---|
| `clump=True` at `threshold=5e-8` | **stored**: made when the Store was built, in its own configuration; no LD job, so fast | computed at r² 0.001 within 3,000 kb |
| `r2` and `kb` given | stored only if both equal the stored configuration; otherwise computed | computed |
| another `threshold` | computed | computed |

Most format 0.3.0 Store Releases carry **stored Clumps** of their 5e-8 tier. On the served Stores they were made at r² equal to the EUR LD Store's `t_far` (about 0.032) within 10,000 kb, in the HGDP+1kGP EUR panel: not the same settings as the computed default. `attrs["clump"]["stored"]` gives each release's configuration. To clump every release the same way, on the fly, give the settings:

```python
leads = og.tophits("OGS-00006:GCST90199621", clump={"r2": 0.001, "kb": 3000})
leads[["rsid", "alid", "z", "p", "clump_size"]]
```

```text
       rsid            alid          z             p  clump_size
  rs1171617 10:59707424:G:T -24.639648 4.751576e-134         210
   rs274548 5:132395115:C:T   9.392578  5.854925e-21         188
rs149235996 5:151340348:A:G   8.125000  4.473624e-16           7
 rs10994001 10:59772198:G:T  -6.326172  2.513179e-10          12
 rs10900223 10:45526183:C:T  -5.986328  2.146312e-09          30
```

```python
leads.attrs["clump"]
```

```text
{'r2': 0.001, 'kb': 3000.0, 'hits': 557, 'leads': 5, 'absent': 110,
 'ld_stores': {'EUR': 'hgdp1kgp-v2-EUR-k10'}}
```

(Recorded before the API reported `source`; it now adds `'source': 'computed'`.)

- **`attrs["clump"]`** has `source` (`stored`, `computed` or `mixed`); `r2`, `kb` and `ld_stores` for the leads clumped on the fly (`None` when none were); the counts `hits`, `leads` and `absent` over both paths, and `imputed`, `ambiguous` and `not_clumped` for hits stored Clumps left out; and `stored`, each stored release's configuration and counts.
- **Computed defaults:** r² 0.001 within 3,000 kb, in the LD Store of each analysis's own ancestry, or EUR when it has none. Choose with a mapping: `clump={"r2": 0.01, "kb": 1000, "ancestry": "EAS"}`, or `"store"` for an LD Store by name (see `og.ld_stores()`).
- **`limit`** then applies to each analysis's leads.
- **`absent`** counts hits the LD Store does not hold. They are not clumped, and not returned.
- **Settings the LD Store cannot answer exactly** are refused with `LDRefusal`, as [`ld_clump`](ld.md#clumping) refuses them. For example, r² 0.001 beyond 3,000 kb is refused, and the message says what the store can answer.
- It is one job. When it clumps on the fly, while its hits wait for an LD worker, its status goes back from `running` to `queued`.

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
