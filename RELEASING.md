# Releasing opengwaspy

Only the owner publishes a release. Agents prepare it: the version bump and the changelog, in a PR.

## Versions

[Semantic versioning](https://semver.org/). Until the Gateway works end to end (#7), releases are `0.x` pre-releases: `0.1.0a1`, `0.1.0a2`, and so on. The version is `__version__` in `src/opengwaspy/__init__.py`; between releases it is a `.dev0` of the next version.

## Steps

1. **Prepare (a PR):**
   - Set `__version__` to the release version, such as `0.1.0a1`.
   - In `docs/changelog.md`, rename "Unreleased" to `## 0.1.0a1`, and add the date on the next line.
   - Run every check locally: `uv run ruff format --check . && uv run ruff check . && uv run mypy && uv run pytest && uv run --group docs mkdocs build --strict`.
   - Run the live check (the `live-check` skill), and record it in `DEVLOG.md`.
   - Merge the PR once CI passes.
2. **Tag (the owner):** `git tag -s v0.1.0a1 -m "opengwaspy 0.1.0a1"` on the merged commit, then `git push origin v0.1.0a1`.
3. **Publish:** the `release` workflow checks that the tag matches the version, builds and checks the wheel, and waits for approval in the `pypi` environment. Once approved, it publishes to PyPI by trusted publishing, and creates a GitHub release (marked as a pre-release for `a`, `b` and `rc` versions) with the changelog section as its notes.
4. **Verify:** `pip install opengwaspy==0.1.0a1` in a clean environment, `python -c "import opengwaspy; print(opengwaspy.__version__)"`, and one live query.
5. **Reopen:** set `__version__` to the next `.dev0` (such as `0.1.0a2.dev0`), and add a new "Unreleased" section to the changelog.

## One-time setup (the owner, #57)

- **On pypi.org**, add a pending trusted publisher for the project `opengwaspy`: owner `opengwas`, repository `opengwaspy`, workflow `release.yml`, environment `pypi`.
- **On GitHub**, in Settings → Environments, create `pypi` with the owner as required reviewer, limited to `v*` tags.

## Withdrawing a release

PyPI files cannot be replaced. To withdraw a broken release, yank it on PyPI (it stays installable only by exact pin), and publish a fixed version.
