# Usage examples

ieugwaspy's usage notebook, rewritten for opengwaspy. The whole script is [`examples/usage_examples.py`](https://github.com/opengwas/opengwaspy/blob/main/examples/usage_examples.py). The output below is from runs against the Data API on 19–21 Nov 2026.

```python
import opengwaspy as og
import opengwaspy.compat as ieugwaspy
```

## Exploring available studies

Search the analyses' labels with `gwasinfo_search`; `limit=None` returns every match:

```python
bmi = og.gwasinfo_search("body mass", limit=None)  # 39 analyses
bmi[["id", "analysis_label", "assigned_ancestry", "sample_size"]].head()
```

```text
                       id   analysis_label assigned_ancestry  sample_size
0    OGS-00011:GCST006802  Body mass index               EUR       119688
1  OGS-00011:GCST90025994  Body mass index               EUR       457756
2  OGS-00011:GCST90029007  Body mass index               EUR       532396
3  OGS-00011:GCST90302889  Body mass index               EUR       365498
4  OGS-00011:GCST90429765  Body mass index               EUR        87908
```

ieugwaspy listed every study with `gwasinfo()` for you to filter. `og.gwasinfo()` still lists all 38,152 analyses, but it takes about 40 requests; searching takes one. See [Metadata: find analyses](guide/metadata.md#find-analyses) for full-text queries and filters.

## Top hits for one study, clumped

ieugwaspy clumped at r² 0.001 within 10,000 kb, which the LD stores cannot answer exactly (see [Migrating](migrating.md#top-hit-clumping)). Here we clump at r² 0.001 within 3,000 kb. The Data API clumps every hit on the server, in one job:

```python
study = bmi.sort_values("sample_size", ascending=False).iloc[0]["id"]  # OGS-00011:GCST90179150
leads = ieugwaspy.tophits([study], r2=0.001, kb=3000)  # 770 independent hits
leads[["rsid", "chr", "position", "ea", "beta", "p"]].sort_values("p").head()
```

```text
UserWarning: 11,793 hits are not in the EUR LD store, so were not clumped or returned
```

```text
         rsid chr   position ea      beta              p
0   rs1421085  16   53767042  C  0.061880   0.000000e+00
1   rs6567160  18   60161902  C  0.043571  5.282378e-180
2  rs13021737   2     632348  A -0.049442  2.002586e-163
3    rs543874   1  177920345  A -0.037656  9.123400e-125
4  rs10938397   4   45180510  A -0.026404   1.177278e-87
```

This analysis has 89,563 genome-wide significant hits. All of them were clumped, except the 11,793 the LD store does not hold: those cannot be clumped, as in ieugwasr, where variants missing from the reference panel were dropped. `leads.attrs["clump"]` has the counts. rs1421085's `p` is 0.0 because it is below 1e-308; its `log10_p` keeps the value.

## Associations of some SNPs in some studies, with proxies

OpenGWAS IDs work: the Data API translates them.

```python
snps = ["rs1421085", "rs6567160", "rs13021737"]
studies3 = ["ukb-b-19953", "ukb-b-2303", "ebi-a-GCST006802"]
ieugwaspy.associations(snps, studies3, proxies=1, r2=0.8, align_alleles=1)[
    ["opengwas_id", "id", "rsid", "ea", "nea", "beta", "p", "proxy"]
]
```

```text
        opengwas_id                     id        rsid ea nea      beta              p  proxy
0       ukb-b-19953  OGS-00009:ukb-b-19953  rs13021737  A   G -0.055125   8.357732e-99  False
1       ukb-b-19953  OGS-00009:ukb-b-19953   rs1421085  C   T  0.073556  4.336199e-291  False
2       ukb-b-19953  OGS-00009:ukb-b-19953   rs6567160  C   T  0.054072  2.317582e-118  False
3        ukb-b-2303   OGS-00009:ukb-b-2303  rs13021737  A   G -0.055052   4.070364e-97  False
4        ukb-b-2303   OGS-00009:ukb-b-2303   rs1421085  C   T  0.073433  7.372227e-286  False
5        ukb-b-2303   OGS-00009:ukb-b-2303   rs6567160  C   T  0.053522  2.558953e-114  False
6  ebi-a-GCST006802   OGS-00011:GCST006802  rs13021737  A   G  0.006398   5.224012e-01  False
7  ebi-a-GCST006802   OGS-00011:GCST006802   rs1421085  C   T -0.025004   3.086451e-05  False
8  ebi-a-GCST006802   OGS-00011:GCST006802   rs6567160  C   T  0.005001   5.371111e-01  False
```

`id` is the Data API's analysis, and `opengwas_id` the ID you asked for. `ebi-a-GCST006802` became `OGS-00011:GCST006802` (an exact match; `attrs["opengwas_ids"]` says so). Every SNP was found in every study, so no proxy was needed. A row with `proxy` true would show the proxy's own SNP, and `target_snp` the one you asked for.

## A PheWAS

```python
phewas = ieugwaspy.phewas(["rs1421085"], pval=1e-5)  # pval is applied on the server
phewas.sort_values("p")[["trait", "beta", "p", "n"]].head()
```

```text
            trait      beta    p       n
449  GCST90479521  0.148952  0.0  607406
347  GCST90476466  0.136496  0.0  425537
346  GCST90476463  0.170333  0.0  425535
450  GCST90479522  0.143887  0.0  607391
345  GCST90476460  0.176294  0.0  425541
```

Some analyses are labelled with their source ID (`GCST…`); `og.gwasinfo(ids)` gives their full metadata.

## chr:pos to rsID

```python
ieugwaspy.variants_to_rsid(["19:44908684", "7:105561135-105563135"])
```

```text
['rs429358', '7:105561135-105563135']
```

Ranges are left as they are. Pass them to `associations`, which fetches every association in the range.
