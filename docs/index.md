# opengwaspy

opengwaspy is the Python client for the [OpenGWAS](https://opengwas.io) Data API. It gives you GWAS summary statistics as pandas DataFrames: analysis metadata, associations, top hits, PheWAS, variants and LD.

It succeeds [ieugwaspy](https://github.com/MRCIEU/ieugwaspy). The new API runs every query as a *job*: you submit the query, the API queues and runs it fairly alongside everyone else's, and you read the result in pages. opengwaspy does all of that for you, so one call gives you one table.

!!! warning "Pre-alpha"
    opengwaspy is under active development and not yet released. Today it provides the
    foundations: configuration, authentication, and running any Data API query as a job.
    Functions for each kind of query, and an ieugwaspy-compatible layer, are coming. Progress
    is on the [project board](https://github.com/orgs/opengwas/projects/1) (Workstream:
    Python client).

## What it does for you

- **Waits politely.** It polls at the interval the API suggests, honours `Retry-After` when the API is busy, and keeps only a few jobs in flight at once.
- **Checks what it reads.** Every page of a result is verified against its checksum.
- **Keeps provenance.** Every DataFrame carries the job, query hash, data releases and result metadata in `DataFrame.attrs`.
- **Never changes your question silently.** If an option cannot be honoured exactly, opengwaspy refuses it and says why, rather than returning a different answer.

## Next

- [Install](install.md)
- [Reference](reference/config.md)
