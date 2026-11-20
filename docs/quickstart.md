# Quickstart

## 1. Install and set your key

```bash
pip install "opengwaspy @ git+https://github.com/opengwas/opengwaspy"
export OPENGWAS_URL=https://...       # the Data API you were given
export OPENGWAS_TOKEN=...             # your developer key
```

See [Authentication](guide/authentication.md) for other ways to set these, and for the Gateway.

## 2. Check who you are

```python
import opengwaspy as og

og.user()
```

```text
{'user': 'developer:opengwaspy', 'role': 'developer', 'tier': 'developer', ...}
```

## 3. Ask a question

Find an analysis:

```python
found = og.gwasinfo_search("carnitine", match="fulltext", store_id="OGS-00006", limit=3)
found[["id", "analysis_label"]]
```

```text
                    id                analysis_label
OGS-00006:GCST90199621              Carnitine levels
OGS-00006:GCST90200791   Creatine to carnitine ratio
OGS-00006:GCST90200805 Spermidine to carnitine ratio
```

The strongest associations of one analysis, carnitine levels:

```python
hits = og.tophits("OGS-00006:GCST90199621")
len(hits)  # 557
hits[["rsid", "alid", "z", "p"]].head(3)
```

```text
     rsid            alid          z             p
rs1171617 10:59707424:G:T -24.639648 4.751576e-134
rs1171614 10:59709780:C:T  24.575195 2.326877e-133
rs1171615 10:59709332:C:T -24.568359 2.753232e-133
```

The call submitted a job, waited for it, read every page of its result, checked each page's checksum, and returned one DataFrame.

## 4. See where the answer came from

Every result carries its provenance in `attrs`:

```python
hits.attrs
```

```text
{'job_id': '45d70a72-8feb-41a5-b53f-b71599c60009',
 'query_hash': 'sha256:444297c0…',
 'endpoint': '/api/tophits',
 'release_id': 'OGS-00006/OGS-00006-completed',
 'releases': [{'store_id': 'OGS-00006', 'release_id': 'OGS-00006-completed'}],
 'metadata': {'threshold': 5e-08, 'observed_only': False, 'total': 557, 'truncated': False},
 'image_digest': 'sha256:8e0f8a1c…',
 ...}
```

Record `releases` with your results: they identify the exact data that answered.

## Next

- [Metadata](guide/metadata.md): what each analysis is.
- [Associations](guide/associations.md), [Top hits and PheWAS](guide/tophits-phewas.md), [Variants](guide/variants.md) and [LD](guide/ld.md).
- [Jobs and large queries](guide/jobs.md): waiting, resuming and cancelling.
