# Migrating from ieugwaspy

opengwaspy replaces [ieugwaspy](https://github.com/MRCIEU/ieugwaspy) 1.0.6. The old OpenGWAS API answered each query directly. The new Data API runs every query as a job, serves different data releases (Stores), and does not do everything the old one did on the server. opengwaspy gives you two ways in:

- **`opengwaspy.compat`** keeps ieugwaspy's function names, arguments and defaults. Use it to move existing code over with few changes:

    ```python
    import opengwaspy.compat as igd  # was: import ieugwaspy as igd
    ```

- **The native functions** (`og.associations`, `og.tophits`, ...) use the Data API's own terms. Use them for new code.

Either way, results are pandas DataFrames, not JSON. The compat functions put ieugwaspy's column names first: `id`, `trait`, `rsid`, `chr`, `position`, `ea`, `nea`, `eaf`, `beta`, `se`, `p`, `n`.

!!! note "Never a silently different answer"
    Where ieugwaspy's behaviour cannot be reproduced exactly on the Data API, opengwaspy
    **refuses** the option and explains what to do, rather than returning a different
    result under the same call.

## Function by function

| ieugwaspy 1.0.6 | `opengwaspy.compat` | Native | Status |
|---|---|---|---|
| `select_api(key)` | `select_api(key)`: `public` is the Gateway, `dev` a local Data API, or a URL | `og.configure(url=...)` | Same |
| `get_jwt()` | `get_jwt()`: saves the token to your user config file (mode 0600), not `.ieugwaspy.json` | `og.configure(jwt=...)` | Differs: where the token is kept |
| `status()` | `status()` | `og.status()` | Differs: the Data API's own status fields |
| `user()` | `user()` | `og.user()` | Differs: the Data API's view of you (`role`, `tier`) |
| `gwasinfo(id=[])` | `gwasinfo(id)`: adds `trait` | `og.gwasinfo(ids)` | Differs: IDs (see below) and columns |
| `gwasinfo_files(id)` | `gwasinfo_files(id)` | `og.gwasinfo_files()` | Not available: no download links; no Store records its source files yet |
| `associations(variant, id, proxies=1, r2=0.8, align_alleles=1, palindromes=1, maf_threshold=0.3)` | same signature; proxies come from the LD stores | `og.associations(variants, analyses)` (no proxies) | Same, with proxies from a different reference panel (HGDP + 1000 Genomes) |
| `tophits(id, pval=5e-8, clump=1, r2=0.001, kb=10000, pop="EUR", ...)` | same signature | `og.tophits(analyses)` (not clumped), then `og.ld_clump` | **Differs: the default clumping is refused** (below) |
| `phewas(variant, pval=1e-3, batch=[])` | same signature; filtered by `pval` here | `og.phewas(variant)` (no p filter) | Same, slower: every association is fetched, then filtered |
| `variants_chrpos(chrpos)` | `variants_chrpos(chrpos)`: the first rsID | `og.variants_chrpos(positions)` | Same |
| `variants_to_rsid(variants)` | `variants_to_rsid(variants)`: returns a new list | (as above) | Same, but does not change its argument |
| `legacy_ids(ids)` | `legacy_ids(ids)` | | Same |

## What differs, and why

### Analysis IDs

OpenGWAS IDs such as `ieu-a-2` or `ukb-b-19953` are not all Data API IDs. A Data API analysis ID is `<store>:<analysis>`, for example `OGS-00009:ukb-b-19953`; the bare `ukb-b-19953` also works when only one Store holds it. IDs that are not served are listed in `attrs["not_found"]` (and printed by `compat.gwasinfo`), never dropped silently. To find analyses, search `og.gwasinfo()` by label:

```python
studies = og.gwasinfo()
studies[studies.analysis_label.str.contains("body mass", case=False)]
```

How every old ID maps to the new ones is still being decided.

### Top-hit clumping

ieugwaspy clumped top hits by default, at r² 0.001 within 10,000 kb, using a full reference panel. The Data API's LD stores hold every r² only within 3,000 kb, and beyond that only r² above a threshold `t_far` (about 0.03; 0.063 for AMR). They cannot tell r² 0.001 from r² 0.02 beyond 3,000 kb, so that default **is refused**, and the error suggests what to ask instead:

```text
UnsupportedOptionError: clumping at r2=0.001 within kb=10000 cannot be done exactly with the EUR LD
store (hgdp1kgp-v2-EUR-k10). Beyond 3,000 kb it holds only pairs with r2 >= 0.0319, so it cannot tell
whether a more distant pair has r2 >= 0.001. Choose one of:
  tophits(..., r2=0.001, kb=3000)   # your r2, within 3,000 kb
  tophits(..., r2=0.04, kb=10000)   # r2 above the store's t_far, up to 10,000 kb
or clump=0 for the unclumped hits.
```

`preclumped`, `bychr` and `force_server` are accepted, and have no effect.

### Proxies

`associations(proxies=1)` works as before. A missing variant is replaced by its best proxy (highest r², then nearest). The proxy is found in the LD store of the analysis's ancestry, where ieugwaspy always used the European 1000 Genomes panel. If no LD store serves an analysis's ancestry, EUR is used, with a warning. Proxy rows carry `proxy`, `target_snp`, `proxy_snp`, `proxy_r2` and the alleles. Their `rsid` and position are the proxy's.

### PheWAS

The Data API has no p-value filter, so `compat.phewas` fetches every association of the variant and filters it here. If one Store holds more than 10,000 associations of the variant (the most the API returns at once), the filter could miss some, so the call is refused. `batch` names Data API Stores (see `og.batches()`), not OpenGWAS batches such as `ieu-a`.

### Columns

| Column | Source |
|---|---|
| `trait` | `analysis_label` |
| `beta` | **Derived:** `z × se`, on the analysis's `stored_effect_scale` (see `gwasinfo`) |
| `p` | **Derived:** `10 ** log10_p`. Below about 1e-308 it is 0.0; `log10_p` keeps the value |
| `n` | **Derived:** the analysis's `sample_size` |
| `ea`, `nea`, `chr` | `effect_allele`, `other_allele`, `chromosome` |

The Data API's own columns are kept beside them.

### Not available

- **Gene lookups** (`variants_gene` in ieugwasr): the Data API has no gene annotation.
- **Allele-frequency reference lookups** (`afl2` in ieugwasr).
- **Download links** for summary statistics files.

## Usage examples

ieugwaspy's usage notebook, rewritten for opengwaspy, is on the [Usage examples](examples.md) page.
