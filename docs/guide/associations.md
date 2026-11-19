# Associations

An association is one variant's effect estimate in one analysis. opengwaspy has three ways to fetch them: by variant, by genomic range, and by whole analysis. Each runs as one or more jobs. opengwaspy splits large requests within the API's limits and puts the rows back together in order.

## By variant

```python
import opengwaspy as og

a = og.associations(["rs1171617", "1:512299:C:CCTGT"], "OGS-00006:GCST90199621")
a[["analysis_id", "rsid", "alid", "effect_allele", "eaf", "z", "se", "log10_p", "p"]]
```

```text
 analysis_id      rsid            alid effect_allele     eaf          z       se     log10_p             p
GCST90199621 rs1171617 10:59707424:G:T             G 0.22991 -24.639648 0.018028 -133.323162 4.751576e-134
```

- **Variants** are rsIDs (`rs1171617`) or ALIDs, `chromosome:position:allele:allele` (`10:59707424:G:T`).
- **A variant absent from an analysis gives no row.** Here `1:512299:C:CCTGT` is not in that analysis. There are no LD proxies here; the ieugwaspy-compatible layer will offer them.
- **`observed_only=True`** (the default) leaves out imputed associations. Pass `False` to include them where a Store holds them; `association_status` says which a row is.
- Up to 1,000 variants and 100 analyses go in one job. More are split into several jobs, run a few at a time. You get one table either way.

## By range

Every association in a stretch of a chromosome:

```python
r = og.associations_range(10, 59_700_000, 59_710_000, "OGS-00006:GCST90199621")
len(r)  # 56
r[["alid", "position", "z", "p"]].head(3)
```

```text
           alid  position         z            p
10:59700295:A:G  59700295  0.720703 4.710922e-01
10:59700496:A:G  59700496 -8.470703 2.439162e-17
10:59700796:A:C  59700796  8.458984 2.697162e-17
```

Positions are one-based and inclusive. A range wider than 10 Mb is split into 10 Mb windows. Without analyses, the range covers every analysis of the `releases` you name.

## Whole analyses

`associations_analysis(analyses)` returns every association of up to 10 analyses per job. It suits Ragged Stores: signals-only and cis-eQTL analyses, up to tens of thousands of rows. A whole Dense or Hybrid analysis (millions of rows) is too large for a job. The API refuses it with `RequestError` (`413 request_too_large`); use `associations_range` instead.

## Columns

| Column | Meaning |
|---|---|
| `analysis_id`, `analysis_label`, `store_id`, `release_id` | Which analysis, and which Store release answered |
| `alid`, `chromosome`, `position`, `rsid` | The variant |
| `effect_allele`, `other_allele`, `eaf` | Alleles, and the effect allele's frequency |
| `z`, `se` | The z-score and standard error, on the analysis's `stored_effect_scale` (see `gwasinfo`) |
| `log10_p` | log10 of the p-value, as the API gives it (−133.3 means p = 10⁻¹³³·³) |
| `p` | **Derived by opengwaspy** as `10 ** log10_p` |
| `association_status` | `observed`, or imputed |

There is no `beta` or `n` column: the API does not serve them. The effect on the stored scale is `z × se`, and sample sizes are in `gwasinfo`.

## Choosing releases

`releases=` limits a query to some Stores. Pass Store IDs (`"OGS-00006"`, meaning its served release), `"store/release"`, or `{"store_id": ..., "release_id": ...}`. `og.batches()` lists what is served.
