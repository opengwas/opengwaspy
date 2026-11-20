# Metadata

`gwasinfo` tells you what each analysis is: its trait, ancestry, sample size, effect scale, source and licence. `gwasinfo_search` finds analyses by what they measure. Metadata calls answer at once; they are not jobs.

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

## Find analyses

`gwasinfo_search` finds analyses whose label contains some text, ignoring case:

```python
bmi = og.gwasinfo_search("body mass index", assigned_ancestry="EUR")
bmi.attrs["total"]  # 26
bmi[["id", "analysis_label", "sample_size"]].head(3)
```

```text
                    id  analysis_label  sample_size
  OGS-00011:GCST006802 Body mass index       119688
OGS-00011:GCST90025994 Body mass index       457756
OGS-00011:GCST90029007 Body mass index       532396
```

The text is literal: it has no wildcards. Rows come in label order, with the same columns as `gwasinfo`.

### Filters

Each filter keeps only the analyses whose field equals it exactly:

| Filter | Example |
|---|---|
| `store_id` | `"OGS-00011"` |
| `assigned_ancestry` | `"EUR"`, `"EAS"` |
| `ancestry_category` | `"EUR"`, `"META"` |
| `outcome_type` | `"binary"` or `"continuous"` |
| `trait_class` | `"phenotype"` |

### Full-text queries

With `match="fulltext"`, the query is a boolean search over the label, trait, consortium, first author and IDs. The best match comes first:

```python
og.gwasinfo_search('"body mass index" AND first_author:loh', match="fulltext")
```

```text
                    id  analysis_label first_author  sample_size
OGS-00011:GCST90029007 Body mass index       Loh PR       532396
```

| Syntax | Matches |
|---|---|
| `obesity asthma` or `obesity AND asthma` | both words |
| `bmi OR obesity` | either word |
| `"body mass" NOT waist` | the phrase, without the word |
| `(bmi OR obes*) AND diabetes` | grouping |
| `obes*` | words starting `obes` |
| `first_author:loh` | a word in one field |
| `"ukb-b-19953"` | an ID: quote IDs that have hyphens |

A full-text search matches whole words: `bmi` does not match `BMI1`, but `bmi*` does. A malformed query raises `RequestError` with `error == "invalid_query"`:

```python
og.gwasinfo_search("bmi AND (", match="fulltext")
```

```text
RequestError: 400 invalid_query: invalid full-text query: fts5: syntax error near ""
```

### How many you get

`limit` (100 by default) is the most analyses returned. `attrs["total"]` counts every match. `limit=None` returns them all, 1,000 per request:

```python
everything = og.gwasinfo_search("body mass", limit=None)
len(everything), everything.attrs["total"]  # (39, 39)
```

- Fetching more than 10,000 analyses warns first.
- The API pages a full-text search only to its 10,000th match. Past that, opengwaspy warns and returns what it has: narrow the query.
- A search too broad for the API's time budget raises `RequestError` with `error == "query_too_broad"`. Use a longer text or a filter.

`attrs` also holds `q`, `match`, `filters`, `release_id` and `catalog_version`.

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

`page.attrs["total"]` is the number of analyses served: 38,152 on 19 Nov 2026. Listing all of them takes about 40 requests, and opengwaspy warns before it does. To find particular analyses, [search](#find-analyses) instead.

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
