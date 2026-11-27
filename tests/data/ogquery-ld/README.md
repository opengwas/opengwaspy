# ogquery's LD Test Panel

The Test Panel's LD Store (`test-panel/store`) and Genotype Store (`test-panel/genotype-store`,
with the pgen fileset it pins: `panel.pgen`, `.psam`, `.pvar`), copied byte for byte from
[ogquery](https://github.com/opengwas/ogquery) `v0.5.0` (`tests/ld/data/test-panel/`), which
holds them from opengwasdb (`tests/ld/data/SOURCE` there). GPL-3.0-only, as opengwaspy is.

The Test Panel is 771 EUR samples over 588 variants of chromosome 22 (`t_far` about 0.027,
`t_partner` 0.01, `near_bp` 3 Mb, `far_bp` 10 Mb, as its provenance records).

A Genotype Store pins each pgen file's size, SHA-256 and `mtime_ns`. A checkout does not keep
mtimes, so the tests copy the panel and set each file's mtime from the pin before opening it,
as ogquery's own tests do.
