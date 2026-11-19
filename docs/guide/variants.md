# Variants

The Data API identifies a variant by its **ALID**: `chromosome:position:allele:allele`, such as `19:44908684:C:T`. Association and LD queries accept ALIDs, and association queries also accept rsIDs. `variants_rsid` and `variants_chrpos` translate between them, using the Stores' own variant tables.

```python
import opengwaspy as og

og.variants_rsid(["rs1171617", "rs429358"], releases="OGS-00006")
```

```text
           alid chromosome effect_allele other_allele  position          release_id      rsid  store_id
10:59707424:G:T         10             G            T  59707424 OGS-00006-completed rs1171617 OGS-00006
19:44908684:C:T         19             C            T  44908684 OGS-00006-completed  rs429358 OGS-00006
```

```python
og.variants_chrpos(["10:59707424", "chr19:44908684"], releases="OGS-00006")  # the same two rows
```

- **One row per variant per Store.** Without `releases`, every served Store is searched (10 per job), so a common variant comes back once per Store that holds it. For one row per variant: `frame.drop_duplicates("alid")`.
- **A multi-allelic rsID** gives one row per allele pair.
- **Exact positions only.** ieugwasr's `radius` is not supported; for a stretch of genome, use `associations_range`.
- **Not dbSNP.** Rows are the Stores' variants, not dbSNP records. An rsID that no Store holds gives no row.
- **No gene lookups.** The Data API has no gene annotation (`variants/gene` answers `501`).
