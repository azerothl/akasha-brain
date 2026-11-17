import asyncio
from uuid import uuid4

import pytest

from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain import project

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


def test_mcp_project_preparation_returns_a_bound_diff_with_no_approval(tmp_path, monkeypatch):
    source = tmp_path / "source"
    other = tmp_path / "other"
    runtime = tmp_path / "runtime"
    for folder in (source, other, runtime):
        folder.mkdir()
    (runtime / "python.exe").touch()
    target = source / "value.py"
    target.write_bytes(b"VALUE = 7\n")
    (source / "check.py").write_bytes(b"from value import VALUE\nassert VALUE == 11\n")
    (source / ".env").write_bytes(b"TOKEN=synthetic\n")

    def verify_copy(stage, portable):
        assert portable == runtime
        assert (stage / "snapshot/value.py").read_bytes() == target.read_bytes()
        return {"status": "passed", "guest_exit_code": 0x4700}

    monkeypatch.setattr(project, "validate_in_sandbox", verify_copy)
    tasks = NotesTasks(tmp_path / "runs", runtime, None, False)
    server = create_server(tasks, project=source)

    async def check():
        tools = {tool.name for tool in await server.list_tools()}
        assert {"project_inspect", "project_prepare", "project_status"} <= tools
        assert "project_apply" not in tools
        for path in ("../other/value.py", ".env"):
            with pytest.raises(ToolError):
                await server.call_tool("project_inspect", {"file": path})

        request = {"target": "value.py", "replacement": "VALUE = 11\n", "test": "check.py"}
        prepared = (await server.call_tool("project_prepare", request)).structured_content
        args = {"proposal_id": prepared["proposal_id"]}

        async def wait():
            while True:
                receipt = (await server.call_tool("project_status", args)).structured_content
                if receipt["status"] not in ("waiting", "running"):
                    return receipt
                await asyncio.sleep(0.01)

        receipt = await asyncio.wait_for(wait(), timeout=5)
        assert receipt["status"] == "awaiting_approval"
        assert not {"approval_sha256", "approved_digest"} & receipt.keys()
        folder = tmp_path / "runs/projects" / prepared["proposal_id"] / "proposal"
        assert receipt["proposal_path"] == str(folder)
        assert receipt["verified_diff"].encode() == (folder / "proposal.diff").read_bytes()
        assert target.read_bytes() == b"VALUE = 7\n"

        other_server = create_server(tasks, project=other)
        with pytest.raises(ToolError, match="inconnu"):
            await other_server.call_tool("project_status", args)
        (folder / "proposal.diff").write_bytes(b"tampered")
        with pytest.raises(ToolError, match="ne correspond pas"):
            await server.call_tool("project_status", args)

    asyncio.run(check())
