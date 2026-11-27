# Downloaded Stores

You can query **Store Releases you have downloaded**, on your own machine, with the same functions and the same results as through the Data API. Large workloads belong here: a local query has no queue, no per-job limits and no allowance.

A **Local Source** reads the releases with [ogquery](https://github.com/opengwas/ogquery), the Store Reader the Data API itself reads Stores with, so the rows are the API's rows.

## Install

The Local Source needs the `local` extra, and Python 3.12 or later:

```bash
pip install "opengwaspy[local] @ git+https://github.com/opengwas/opengwaspy"
```

It adds ogquery, with numpy, zarr and numcodecs, all as wheels, on Linux, macOS and Windows. Without it, `og.local()` says what to install.

## Open releases and query them

Give the full path of each Store Release: the directory holding its `manifest.json`. Pass the Local Source as `client`:

```python
import opengwaspy as og

with og.local(["/data/stores/OGS-00006/<release_id>"]) as source:
    rows = og.associations(["rs1205"], ["OGS-00006:GCST90199621"], client=source)
    region = og.associations_range("7", 105_000_000, 106_000_000, client=source)
    whole = og.associations_analysis("OGS-00006:GCST90199621", client=source)
```

Switching between the API and your downloads is that one argument.

- **One release per Store.** A Local Source holds at most one release of each GWAS Store, so no query chooses between releases. Two releases of one Store are refused when you open them.
- **Analyses are named as with the API:** `store_id:analysis_id`, or a bare analysis ID that only one of the open releases holds. A bare ID in several is refused as ambiguous.
- **OpenGWAS IDs** (`ieu-a-2`) are not translated locally: the releases don't carry them. Translate them with `og.gwasinfo([...])` on the API, then use the `store_id:analysis_id` it gives.
- **Format 0.3.** A release of an older format is refused, with how to update it.
- **The same rows.** Columns, order and missing values are the API's (non-finite statistics are missing, as the API writes them `null`). `attrs["source"]` is `"local"`, with the releases, their paths and the ogquery version, in place of a job ID.
- **No limits of its own.** A function that splits a large request into several API jobs sends it whole to a Local Source. A whole Dense analysis is millions of rows: mind your memory.
- **Close it** (or use `with`) to let go of the files.

## What a Local Source answers

| Function | Local Source |
|---|---|
| `associations`, `associations_range`, `associations_analysis` | yes |
| `tophits`, `phewas`, `variants_rsid`, `variants_chrpos`, metadata | coming next (#114) |
| stored Clumps, `rho`, HapMap3 | coming (#115) |
| LD from downloaded LD Stores | coming (#116) |
| `gwasinfo_search`, `status`, `user`, the API's LD Stores | no: they need the Data API |

A function it can't answer raises `LocalUnsupported`, naming the function. It never asks the Data API instead.
