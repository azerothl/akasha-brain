import asyncio
from uuid import uuid4

import pytest

from akasha_brain.desktop_tasks import NotesTasks

pytest.importorskip("mcp.server.mcpserver")

from mcp.server.mcpserver.exceptions import ToolError

from akasha_brain.mcp_server import create_server


def test_mcp_exposes_structured_notes_tools_and_refuses_unconfigured_runs(tmp_path):
    directory = tmp_path / "runs"
    server = create_server(NotesTasks(directory, None, None, False))

    async def check():
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert set(tools) == {"notes_plan", "notes_start", "notes_status"}
        assert all(tool.output_schema for tool in tools.values())
        assert tools["notes_start"].input_schema["properties"] == {}

        plan = (await server.call_tool("notes_plan", {})).structured_content
        assert plan["runtime_ready"] is False
        assert plan["graph"]["environment_id"] == "bench-notes"

        with pytest.raises(ToolError, match="Python portable"):
            await server.call_tool("notes_start", {})
        with pytest.raises(ToolError, match="inconnu"):
            await server.call_tool("notes_status", {"task_id": str(uuid4())})

    asyncio.run(check())
    assert not directory.exists()
