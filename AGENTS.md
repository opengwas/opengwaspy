# Agent instructions

## Mission

Build `opengwaspy`, the Python client for the OpenGWAS Data API, as described in `REQUIREMENTS.md`. Treat that file as the source of truth for scope, behaviour and acceptance.

`opengwaspy` succeeds [ieugwaspy](https://github.com/MRCIEU/ieugwaspy) (checked out read-only at `/home/eptrg/repos/ieugwaspy`). It replicates ieugwaspy's functionality on the new, job-based API served by [ogdb-api](https://github.com/opengwas/ogdb-api) (checked out at `/home/eptrg/repos/ogdb-api`). In production, the API is reached through the [Gateway](https://github.com/opengwas/opengwas-gateway).

Never make the client silently return different science from what the caller asked for. If an option cannot be honoured, either compose it faithfully on the client from server operations, or refuse it with a clear error. Do not ignore it.

## Persistence documents

- Read `REQUIREMENTS.md` before changing code.
- Read `WORKPLAN.md` for the owner's decisions and context. Take the next item of work from the project board (see "Project board").
- Append meaningful progress, decisions, evidence, test results and blockers to `DEVLOG.md`, newest entry first.
- Keep `WORKPLAN.md` current: record the owner's new design decisions and new epics there. It does not track status; the board does.
- Never use these documents to hide failures. Record failed commands and unresolved risks plainly.

## Upstream contracts

The API is not ours to change. Read these before working on any endpoint:

| Document | What it gives |
|---|---|
| `../ogdb-api/SPECIFICATION.md` | The Data API's product contract: limits, errors, queue, LD (§9.3) |
| `../ogdb-api/docs/gateway-contract.md` | Keys, headers, the job flow, `JobStatus`, error codes, cost headers |
| `../ogdb-api/docs/client-mapping.md` | Every ieugwasr/ieugwaspy call mapped to the Data API, and which defaults change results |
| `../ogdb-api/docs/guide/` | The user guide, including the reference client `ogdb.py` |
| `http://host.lima.internal:6433/openapi.json` (`/docs`, `/redoc`) | The live, machine-readable schema |
| `../opengwas-gateway` (not checked out; clone to the scratchpad) | How the Gateway authenticates users, its `/ogdb` prefix, and its rate limits |

- Do not edit anything outside `/home/eptrg/repos/opengwaspy` unless the owner authorises it.
- Never switch branches in, reset, or leave edits in `../ogdb-api`: the host deploys from that checkout.
- If the API is wrong or missing something the client needs, file an issue on `opengwas/ogdb-api` (with approval), link it from the opengwaspy ticket, and work around it or block on it. Do not paper over it in the client.
- Record the upstream commit or `image_digest` you tested against in `DEVLOG.md`.

## Project board

Planned work is tracked on the [OpenGWASDB project board](https://github.com/orgs/opengwas/projects/1) under the **Python client** workstream. The board is the single record of status. Its README sets the rules for epics, tickets as sub-issues, blocking links, labels and closing.

- **Read the rules first.** Read the board README before filing or changing issues: `gh project view 1 --owner opengwas --format json --jq .readme`. If the README and this file disagree about the board, the README wins.
- **Work from an issue.** Take work from an open ticket in `opengwas/opengwaspy`. Name the issue in the branch (`<n>-short-name`), and put `Closes #n` in the PR.
- **Keep the board current as work moves.**
  - Set an epic to Active when its first ticket starts.
  - Keep the epic's **Next** field to one line saying what happens next or what it waits on.
  - When a ticket's work reaches `main`, close the ticket with a comment giving the evidence (tests, commit, DEVLOG entry).
  - When an epic's last ticket closes, close the epic and set it to Done.
- **File discoveries.** A follow-up found mid-work becomes a sub-issue of its epic, not only a WORKPLAN line. An API problem becomes an `opengwas/ogdb-api` issue, linked as blocking.
- **Use the board skill** (`/board`; script `~/.agents/skills/board/scripts/board.py`):
  - `report` measures the board and changes nothing;
  - `set KEY Field=Value` updates fields;
  - `apply CHANGES.json --dry-run`, then without `--dry-run`, applies a set of changes;
  - `post-update` posts a status update.
- **Ask before outward changes.** Get the owner's approval before closing epics, re-parenting issues, posting a status update, publishing docs for the first time, or publishing to PyPI. Filing tickets under an approved epic, and closing tickets with evidence, need no further approval.
- **What stays in the repo.** `WORKPLAN.md` points at the issues and records the owner's design decisions. `DEVLOG.md` holds the evidence. Neither keeps a second copy of the board's status.

## Environment

Agents run inside a lima VM on the owner's workstation. `/home/eptrg/repos` is mounted read-write from the host.

| Instance | URL from the VM | What agents may do |
|---|---|---|
| The host's Data API | `http://host.lima.internal:6433` | Read-only and acceptance queries with the `opengwaspy` developer key. No stress or saturation load: keep integration tests small, and run them serially. |
| The VM's dev Data API | `http://localhost:7433` | Owned by the ogdb-api agents. Use it only if the owner says so. |
| The Gateway | not yet reachable from the VM | Gateway tests wait for epic "opengwaspy works through the Gateway". |

- **Credentials** live in `opengwaspy/.env` (gitignored; see `.env.example`): `OPENGWAS_URL` and `OPENGWAS_TOKEN`. Never print, log or commit a key, and never read `../ogdb-api/.env`.
- **Which instance answered:** `GET /api/status` gives `execution.image_digest`. Record it with integration evidence.
- **Ports:** nothing in the VM may listen on 6432, 6433 or 6434 (lima forwards VM ports to the host). Serve the docs preview on 8765.
- **Tools:** `uv` and `gh` are in `~/.local/bin`. Use `uv` for the virtualenv and Python versions (`uv sync`, `uv run pytest`, `uv run --python 3.10 ...`). The system Python has no pip.

## Repo-local skills

Under `.agents/skills/`, linked from `.claude/skills/`:

| Skill | Use it to |
|---|---|
| `live-check` | Run the integration tests and doc examples against the live API, safely, and record the evidence |
| `api-drift` | Compare the live OpenAPI schema with the client's snapshot and models, and report what changed |
| `docs-site` | Build, check, preview and deploy the MkDocs site on GitHub Pages |

## Working practices

1. Inspect the repository and existing changes before editing. Preserve unrelated work.
2. Make the smallest coherent change that advances one ticket.
3. **Test first.** Unit tests use recorded or hand-written responses (`respx`/fixtures), never the network. Integration tests are marked `@pytest.mark.live` and are skipped without credentials.
4. Type the public API (`py.typed`, mypy strict on `src/`), and write a docstring on every public function: the docs are generated from them.
5. Keep the transport (HTTP, auth, retries, jobs) separate from the operations, and the operations separate from the ieugwaspy-compatible layer.
6. Treat the job flow's contract carefully: polling at `poll_after_seconds`, honouring `Retry-After`, paging every result, resubmission returning the existing job, and cancellation.
7. Never log tokens, or the `Authorization` header.
8. Do not weaken tests, remove safety limits, or turn unsupported functionality into misleading placeholders.
9. For external facts or changing contracts, verify the source and record the URL and date in `DEVLOG.md`.

## Checks

Before every commit:

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest                      # unit tests, offline
uv run mkdocs build --strict       # when docs or docstrings changed
```

Before closing a ticket that touches API behaviour, also run `uv run pytest -m live` (see the `live-check` skill).

## Git discipline

- Work on a branch per ticket; open a PR into `main` with `Closes #n`. Commit directly to `main` only with the owner's approval.
- Do not stack PRs on another PR's branch: merging with `--delete-branch` closes the stacked PR. Branch from `main`, or wait.
- **Merge only when every check reports pass.** `main` has no branch protection, so `gh pr merge` succeeds even when a check failed. Verify first (for example `gh pr checks <n> --json bucket --jq 'all(.[]; .bucket=="pass" or .bucket=="skipping")'`), and run the full local checks, `ruff format` included, even for docs-only changes: ruff formats Python blocks in Markdown.
- You may merge your own PR once its checks pass, unless it makes a breaking change to the public API or needs human input (a decision, a credential, a first publication). Then ask the owner.
- Each commit has one purpose and passes the checks. Use the repository's configured git identity: name `Claude -- t0mrg`, email t0mrg's GitHub noreply address, so that the CLA check links the commits to the allow-listed t0mrg (owner, 19 Nov 2026). Never change the CLA workflow's allow-list yourself.
- Inspect the diff and status before committing: `git diff --check`, `git status --short`, then `git add <scoped files>`.
- Never use destructive history operations unless explicitly requested.
- Record commit hashes in `DEVLOG.md`.

## Definition of done

A ticket is done when the implementation, tests, docstrings and user documentation are addressed; the checks pass; `DEVLOG.md` contains the evidence (including the live run and the API's `image_digest` where relevant); and the work has reached `main`. At handoff, report the remaining risks and the commands run.
