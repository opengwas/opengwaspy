# Install

opengwaspy needs Python 3.10 or later.

It is not yet on PyPI. Until the first release, install it from GitHub:

```bash
pip install "opengwaspy @ git+https://github.com/opengwas/opengwaspy"
```

or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add "opengwaspy @ git+https://github.com/opengwas/opengwaspy"
```

It depends on [httpx](https://www.python-httpx.org/) and [pandas](https://pandas.pydata.org/).

## Credentials

Set where the API is, and your key, in the environment:

```bash
export OPENGWAS_URL=https://...      # the Data API, or the Gateway once it is live
export OPENGWAS_TOKEN=...            # a Data API developer key
```

See [Authentication](guide/authentication.md) for every setting, the config file, and the Gateway. Then try the [Quickstart](quickstart.md).
