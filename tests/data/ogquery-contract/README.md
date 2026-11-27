# ogquery's Store Reader contract releases

Five of the eleven Store Releases of the Store Reader contract bundle (bundle 2, format
0.3.0), copied byte for byte from [ogquery](https://github.com/opengwas/ogquery)
`v0.5.0` (`tests/contract/releases/`), which holds them from opengwasdb at the commit in
`SOURCE`. They are GPL-3.0-only, as opengwaspy is.

| Release | Layout | Holds |
|---|---|---|
| `dense_ranges` | Dense | 8 variants on chromosomes 1, 2 and X, three at one position; a multi-allelic rsID (`rs5000`); an infinite SE (`1:1000:A:G`); Analysis `bmi_irn` |
| `ragged_ranges` | Ragged | the same 8 variants, signals-only; Analysis `trait_a` |
| `hybrid_ranges` | Hybrid | the same 8 variants, 4 on the Dense Component's panel and 4 in the Overflow; Analysis `bmi_irn` |
| `dense_rho` | Dense | four Analyses (`trait_a` to `trait_d`) and a Rho Matrix: `trait_a`–`trait_b` 0.617, `trait_c` and `trait_d` without support (NaN) |
| `hybrid_overflow_only` | Hybrid | the same four, `trait_c` Overflow-only (no Rho: refused), and a Rho Matrix in the Dense Component |

Every release's manifest names Store `s`; the tests copy them and give each its own Store
ID where they need several. Refresh them from a new ogquery tag when the bundle changes.
