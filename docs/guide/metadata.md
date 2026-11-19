# Metadata

`gwasinfo` tells you what each analysis is: its trait, ancestry, sample size, effect scale, source and licence. Metadata calls answer at once; they are not jobs.

## Look up analyses

Pass analysis IDs. They come back in the order you gave:

```python
import opengwaspy as og

info = og.gwasinfo(["OGS-00006:GCST90199621", "ieu-a-2"])
info[["id", "analysis_label", "assigned_ancestry", "sample_size", "stored_effect_scale"]]
```

```text
                    id   analysis_label assigned_ancestry  sample_size stored_effect_scale
OGS-00006:GCST90199621 Carnitine levels               EUR         8192                  sd
```

An analysis ID is `<store>:<analysis>`, such as `OGS-00006:GCST90199621`. You can also pass the bare analysis ID (`GCST90199621`). If several Stores hold it, you get one row from each.

IDs that no served Store holds are not an error. They are listed in `attrs`:

```python
info.attrs["not_found"]
```

```text
['ieu-a-2']
```

Pass `strict=True` to raise `RequestError` instead.

!!! note "OpenGWAS IDs"
    IDs from the old OpenGWAS API, such as `ieu-a-2`, are not Data API analysis IDs. How old IDs map to new ones is still being decided.

## List analyses

Without IDs, `gwasinfo` lists the served analyses, 1,000 per request:

```python
page = og.gwasinfo(limit=3)
page[["id", "analysis_label"]]
```

```text
                    id     analysis_label
OGS-00006:GCST90199621   Carnitine levels
OGS-00006:GCST90199622    Benzoate levels
OGS-00006:GCST90199623 Maltotriose levels
```

`page.attrs["total"]` is the number of analyses served: 38,152 on 19 Nov 2026. Listing all of them takes about 40 requests, and opengwaspy warns before it does.

## Columns

Each row has, among others:

| Column | Meaning |
|---|---|
| `id`, `store_id`, `analysis_id` | The analysis, its Store, and its ID within the Store |
| `analysis_label`, `trait_ontology_id`, `trait_ontology_label` | What was measured |
| `assigned_ancestry`, `source_ancestry_label` | The ancestry the Store assigned, and the source's own label |
| `sample_size`, `n_cases`, `n_controls` | Sample sizes |
| `stored_effect_scale`, `original_effect_scale`, `original_sd` | How effects are scaled |
| `publication_pmid`, `publication_doi`, `first_author`, `consortium`, `license` | Source and terms |

`attrs` also holds `release_id` (the Store releases that answered) and `catalog_version`.

## Source files

`gwasinfo_files()` lists the source files a page of analyses was built from (name, checksum and size). ieugwaspy's `gwasinfo_files` returned download links instead; the Data API has none. On 19 Nov 2026 no served Store records its source files, so the call raises `NotImplementedByServer`.
