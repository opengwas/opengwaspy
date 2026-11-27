# Use with AI assistants

opengwaspy includes an [MCP](https://modelcontextprotocol.io/) server. With it, an AI assistant can use OpenGWAS for you: Claude Code, Claude Desktop, or any other MCP client. The assistant can find analyses, fetch top hits, look up associations, run a PheWAS and query LD, all through opengwaspy's tested functions, with your own credential.

The server runs on your computer, started by the assistant, and talks to it over stdio. Every tool only reads data.

## Install

The server needs the `mcp` extra. opengwaspy is not yet on PyPI, so install it from GitHub:

```bash
pip install "opengwaspy[mcp] @ git+https://github.com/opengwas/opengwaspy"
opengwaspy-mcp --help
```

Or let [uv](https://docs.astral.sh/uv/) fetch and run it, with nothing installed:

```bash
uvx --from "opengwaspy[mcp] @ git+https://github.com/opengwas/opengwaspy" opengwaspy-mcp
```

## Credentials

The server uses the usual opengwaspy configuration (see [Authentication](authentication.md)). Never paste a credential into the chat, and never give one to the assistant: no tool takes one, and none is ever shown.

**Users: an OpenGWAS token, through the Gateway.** Get a token from your [OpenGWAS profile](https://api.opengwas.io/profile/), and save it in your opengwaspy config file:

```bash
python -c "import opengwaspy.compat as c; c.get_jwt()"   # opens the profile page; paste the token
```

Then add `profile = "gateway"` to the config file (`~/.config/opengwaspy/config.toml` on Linux):

```toml
profile = "gateway"
jwt = "..."
```

A token lasts 14 days, and getting a new one revokes the old. When it expires, a tool says so. Save the new token the same way, and the running server uses it on the next call, with no restart. You can also set the token as `OPENGWAS_JWT` in the assistant's MCP settings, but then a new token needs a change there, and a restart.

**Developers: a Data API developer key.** Set `OPENGWAS_URL` and `OPENGWAS_TOKEN`, as for opengwaspy itself.

If nothing is configured, the server still starts, and its tools explain how to set a credential.

## Add it to your assistant

### Claude Code

```bash
claude mcp add opengwas -- opengwaspy-mcp
```

With uvx instead of an installed package:

```bash
claude mcp add opengwas -- uvx --from "opengwaspy[mcp] @ git+https://github.com/opengwas/opengwaspy" opengwaspy-mcp
```

Add `--scope user` to use it in every project. Saved files go to `opengwas-results` in the folder Claude Code runs in.

### Claude Desktop

Add the server to `claude_desktop_config.json` (Settings → Developer → Edit Config), then restart Claude Desktop:

```json
{
  "mcpServers": {
    "opengwas": {
      "command": "uvx",
      "args": [
        "--from",
        "opengwaspy[mcp] @ git+https://github.com/opengwas/opengwaspy",
        "opengwaspy-mcp"
      ],
      "env": {
        "OPENGWAS_MCP_OUTPUT_DIR": "/Users/you/opengwas-results"
      }
    }
  }
}
```

Give `uvx` as a full path (from `which uvx`) if Claude Desktop cannot find it. Set `OPENGWAS_MCP_OUTPUT_DIR` to an absolute folder: Claude Desktop's working folder is not one you choose.

### Other MCP clients

Run `opengwaspy-mcp` as a stdio server. It takes `--url` and `--profile`; everything else comes from the environment and the config file.

## Tools

| Tool | What it does | Limits |
|---|---|---|
| `api_status` | Which API is in use, whether it is ready, who you are signed in as, your allowance, the LD panels and the data releases | |
| `search_analyses` | Find analyses by label, or by a full-text query, with filters | 100 rows |
| `get_analyses` | Metadata of analyses by ID; OpenGWAS IDs (`ieu-a-2`, `ukb-b-19953`) are translated | 100 IDs |
| `top_hits` | The strongest associations of analyses, optionally LD-clumped on the server | 10 analyses |
| `associations` | Associations of variants in analyses, optionally with LD proxies | 100 variants × 20 analyses |
| `region_associations` | Every association in a region | 1 Mb × 5 analyses (10 Mb with `save_as`) |
| `phewas` | One variant across every analysis, at p ≤ 1e-8 by default | 1,000 rows per job (10,000 with `save_as`) |
| `variant_info` | Variants by rsID or position: ALID, alleles, Stores | 100 variants |
| `ld_proxies` | Variants in LD with given variants | 100 variants |
| `ld_matrix` | Signed r between every pair of variants | 50 variants |
| `get_job_result` | Pick up a call that was still running | |

Variants may be rsIDs or ALIDs (`chromosome:position:allele:allele`).

Each answer gives:

- a one-line summary, with how many rows there were in all;
- the main columns;
- up to `max_rows` rows (50 by default, at most 100);
- notes to pass on, such as OpenGWAS IDs translated to a later release, or variants an LD panel lacks;
- provenance: releases, jobs, the API build, and your remaining allowance.

`columns="all"` gives every column. Limits are checked before any query is sent. The API's refusals (for example, an LD window the panel cannot answer exactly) come back as errors that say what it can answer instead.

## Saving full results

Every data tool takes `save_as`, a file name. The full result is written as CSV, with every row and column. A `.json` file beside it records the tool, its arguments, the summary, the notes and the provenance.

- Files go in one folder: `OPENGWAS_MCP_OUTPUT_DIR`, or `opengwas-results` in the server's working folder. It is created when first needed.
- Names are reduced to letters, digits, `.`, `_` and `-`, and given `.csv`.
- Paths, `..` and symbolic links are refused, so nothing is written outside the folder.
- An existing file is replaced only with `overwrite`.

Ask for `save_as` when you want the data for your own analysis, rather than asking the assistant to read thousands of rows.

## Long jobs

Queries run as jobs on the API. The server reports their progress to the assistant (submitted, queued, running, pages read).

A call still running after 60 seconds (`OPENGWAS_MCP_WAIT_SECONDS`) answers `status: "running"` with its job IDs, and the jobs keep running. The assistant then calls `get_job_result` with any of those IDs. That runs the same call again: the API returns the jobs it already has, so nothing is computed twice. If you cancel a call in the assistant, its jobs are cancelled on the API.

## Allowance

Through the Gateway, each answer shows how much of your allowance is left, and when it resets. When it runs out, tools fail at once and say when it resets, rather than leaving the assistant waiting.

## Privacy

- Your queries go to OpenGWAS with your credential, as they would from opengwaspy in Python. The assistant decides which queries to run.
- Results, including analysis metadata, enter the assistant's context, and so reach its provider (for example, Anthropic for Claude), under that provider's terms.
- Credentials stay on your computer: no tool takes one, outputs are scrubbed of them, and the server never logs them.
- Text from the API, such as trait names, is passed to the assistant as data. The server tells the assistant not to treat it as instructions.

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `OPENGWAS_JWT`, `OPENGWAS_TOKEN`, `OPENGWAS_URL`, `OPENGWAS_PROFILE`, `OPENGWAS_CONFIG` | As for opengwaspy: see [Authentication](authentication.md) | |
| `OPENGWAS_MCP_OUTPUT_DIR` | Where `save_as` writes | `./opengwas-results` |
| `OPENGWAS_MCP_WAIT_SECONDS` | How long a call waits for its jobs | `60` |
