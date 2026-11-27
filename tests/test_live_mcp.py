"""Live: the MCP server over stdio, as an assistant would use it, with the developer key.

The OpenGWAS token (JWT) path through the Gateway waits on #7.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client, StdioServerParameters

from tests.conftest import LiveAPI

pytestmark = pytest.mark.live


def test_search_tophits_associations_and_save(live_api: LiveAPI, tmp_path: Path) -> None:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "OPENGWAS_URL": live_api.url,
        "OPENGWAS_TOKEN": live_api.token,
        "OPENGWAS_CONFIG": str(tmp_path / "none.toml"),
        "OPENGWAS_MCP_OUTPUT_DIR": str(tmp_path / "results"),
        "OPENGWAS_MCP_WAIT_SECONDS": "120",
    }
    server = StdioServerParameters(command=sys.executable, args=["-m", "opengwaspy.mcp"], env=env)

    async def main() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async with Client(server) as mcp:

            async def tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
                result = await mcp.call_tool(name, args)
                text = "\n".join(getattr(c, "text", "") for c in result.content)
                assert not result.is_error, f"{name}: {text}"
                assert live_api.token not in text
                body: dict[str, Any] | None = result.structured_content
                assert body is not None and body.get("status", "done") == "done", body
                out.append(body)
                return body

            found = await tool(
                "search_analyses",
                {"q": "body mass index", "assigned_ancestry": "EUR", "max_rows": 5},
            )
            analysis = found["rows"][0]["id"]
            leads = await tool("top_hits", {"analysis_ids": [analysis], "clump": True})
            assert leads["rows"] and "clump_size" in leads["columns"]
            assert leads["provenance"]["clump"]["leads"] >= 1
            rsids = [r["rsid"] for r in leads["rows"][:5] if r.get("rsid")]
            await tool(
                "associations",
                {"variants": rsids, "analysis_ids": [analysis], "save_as": "lead-associations"},
            )
        return out

    found, _, saved = anyio.run(main)
    assert found["total_rows"] >= 1
    file = Path(saved["saved"]["path"])
    assert file.parent == (tmp_path / "results").resolve()
    assert file.read_text().startswith("id,")
    sidecar = json.loads(Path(saved["saved"]["provenance_path"]).read_text())
    assert sidecar["tool"] == "associations"
    assert live_api.token not in json.dumps(sidecar)
