# LD

The Data API serves linkage disequilibrium (LD) from **LD Stores**, one per ancestry, built from the HGDP + 1000 Genomes reference panel.

```python
import opengwaspy as og

og.ld_stores()[["store", "ancestry", "n", "t_far", "near_bp", "far_bp"]]
```

```text
              store ancestry   n    t_far  near_bp   far_bp
hgdp1kgp-v2-EUR-k10      EUR 665 0.031865  3000000 10000000
hgdp1kgp-v2-AFR-k10      AFR 608 0.034908  3000000 10000000
hgdp1kgp-v2-EAS-k10      EAS 724 0.029229  3000000 10000000
hgdp1kgp-v2-SAS-k10      SAS 672 0.031528  3000000 10000000
hgdp1kgp-v2-AMR-k10      AMR 341 0.063152  3000000 10000000
```

Name a store by `ancestry="EUR"`, or by `store=`. Variants are **ALIDs** (`chromosome:position:allele:allele`), not rsIDs; [`variants_rsid`](variants.md) finds an rsID's ALID.

## What a store holds

- Within `near_bp` (3 Mb) of a variant, **every** r.
- From `near_bp` to `far_bp` (10 Mb), only pairs with r² ≥ `t_far` (about 0.03; 0.063 for AMR). The rest are known only to be below `t_far`.
- Beyond `far_bp`, or across chromosomes, nothing.

A pair the store does not hold is `NaN`, never 0, unless you pass `fill=`. A request the store cannot answer exactly is refused with `LDRefusal` before any job runs. The error says what the store can answer instead.

## Matrix

```python
signal = ["10:59707424:G:T", "10:59709780:C:T", "10:59709332:C:T", "1:1:A:G"]
m = og.ld_matrix(signal, ancestry="EUR")
m.round(3)
```

```text
                 10:59707424:G:T  10:59709780:C:T  10:59709332:C:T
alid
10:59707424:G:T            1.000           -0.988            0.988
10:59709780:C:T           -0.988            1.000           -1.000
10:59709332:C:T            0.988           -1.000            1.000
```

`m.attrs["absent"]` is `['1:1:A:G']`, the ALID the store does not hold. Values are signed r; the sign refers to the alleles in `m.attrs["variants"]` (`a1`, `a2`). Square r for r². A matrix takes up to 500 ALIDs, and opengwaspy never splits one: the pairs between the parts would be lost.

`ld_region(chromosome, centre, radius, ancestry=...)` gives the matrix of every variant the store holds in a region, up to 2,000 variants.

## Proxies

```python
og.ld_proxies("10:59707424:G:T", ancestry="EUR", kb=100).head(3)
```

```text
 distance           proxy           query         r       r2
     1407 10:59708831:G:T 10:59707424:G:T  0.992172 0.984406
     1908 10:59709332:C:T 10:59707424:G:T  0.988258 0.976655
     2356 10:59709780:C:T 10:59707424:G:T -0.988258 0.976655
```

The defaults are `r2=0.8` and `kb=10000`. More than 1,000 ALIDs are split into several jobs.

## Clumping

Clumping keeps the strongest variant of each group in LD. Give one score per ALID, higher meaning stronger, such as |z|:

```python
og.ld_clump(signal[:3], [24.6, 24.5, 24.5], r2=0.1, kb=1000, ancestry="EUR")
```

```text
           alid chromosome            lead  position         r  score
10:59707424:G:T         10 10:59707424:G:T  59707424  1.000000   24.6
10:59709780:C:T         10 10:59707424:G:T  59709780 -0.988258   24.5
10:59709332:C:T         10 10:59707424:G:T  59709332  0.988258   24.5
```

The three top hits of the [top hits](tophits-phewas.md) example are one clump, led by `10:59707424:G:T`. The leads are `frame[frame.alid == frame.lead]`.

`r2` and `kb` are required. **ieugwaspy's and ieugwasr's default, r² 0.001 within 10,000 kb, is refused**, because beyond 3 Mb the store cannot tell r² = 0.001 from r² = 0.03:

```python
og.ld_clump(signal[:1], [3.0], r2=0.001, kb=10_000, ancestry="EUR")
```

```text
LDRefusal: 422 ld_refusal: r2=0.001 is below t_far=0.03186544342507645: beyond 3,000,000 bp the store
holds only the Bound r² < t_far for unstored pairs, which does not decide r̂² ≥ r2 (request …).
This store answers r2 >= 0.0319 with kb up to 10,000, or any r2 with kb up to 3,000
```

So clump with `r2=0.001, kb=3000`, or `r2=0.05, kb=10000` (above every store's `t_far` but AMR's; for AMR use 0.07).

## Reference lookup

`ld_reflookup(alids, ancestry=...)` gives, for each ALID, whether the store holds it (`present`).
