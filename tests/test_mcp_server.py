import asyncio
from base64 import b64decode
from hashlib import sha256
from uuid import uuid4

import pytest

from akasha_brain.desktop_tasks import NotesTasks
from akasha_brain import image_assets, image_cli, project
from akasha_brain.capability_recovery import Recovery
from akasha_brain.image_execution import ImageResult
from akasha_brain.project_common import ProjectError

pytest.importorskip("mcp.server.mcpserver")

from mcp.server.mcpserver.exceptions import ToolError

from akasha_brain.mcp_server import create_server


def test_mcp_exposes_structured_notes_tools_and_refuses_unconfigured_runs(tmp_path):
    directory = tmp_path / "runs"
    server = create_server(NotesTasks(directory, None, None, False))

    async def check():
        tools = {tool.name: tool for tool in await server.list_tools()}
        assert set(tools) == {"notes_plan", "notes_start", "notes_status",
                              "image_start", "image_resume", "image_status", "image_result"}
        assert all(tool.output_schema for tool in tools.values())
        assert tools["notes_start"].input_schema["properties"] == {}
        assert set(tools["image_start"].input_schema["properties"]) == {"prompt"}
        assert set(tools["image_resume"].input_schema["properties"]) == {"task_id"}

        plan = (await server.call_tool("notes_plan", {})).structured_content
        assert plan["runtime_ready"] is False
        assert plan["graph"]["environment_id"] == "bench-notes"

        with pytest.raises(ToolError, match="Python portable"):
            await server.call_tool("notes_start", {})
        with pytest.raises(ToolError, match="inconnu"):
            await server.call_tool("notes_status", {"task_id": str(uuid4())})

    asyncio.run(check())
    assert not directory.exists()


def test_mcp_image_waits_for_each_artifact_and_returns_verified_content(tmp_path, monkeypatch):
    runs = tmp_path / "image-runs"
    server = create_server(NotesTasks(tmp_path / "runs", None, None, False), image_runs=runs)
    png = b"synthetic PNG supplied by the isolated backend"
    proof = {"status": "passed", "png": {"bytes": len(png), "sha256": sha256(png).hexdigest()}}
    installed = set()

    def generate(state, prompt, project, consent):
        assert state.database == runs.resolve() / "capability-recovery.sqlite"
        assert prompt == "Selfie de chat" and project is None and consent is None
        for artifact in (image_assets.ENGINE, image_assets.MODEL):
            if artifact not in installed:
                return image_assets.review_download(runs / "image-engine", artifact)
        return ImageResult(png, {**proof, "png": {**proof["png"], "sha256": "0" * 64}} if corrupt else proof)

    corrupt = False
    monkeypatch.setattr(Recovery, "generate_image", generate)

    async def check():
        nonlocal corrupt

        async def poll(args):
            while True:
                response = await server.call_tool("image_status", args)
                report = response.structured_content
                if report["status"] not in {"waiting", "running"}:
                    return report
                await asyncio.sleep(0.01)

        with pytest.raises(ToolError, match="1 500"):
            await server.call_tool("image_start", {"prompt": " "})
        start = (await server.call_tool("image_start", {"prompt": " Selfie de chat "})).structured_content
        args = {"task_id": start["task_id"]}
        first = await asyncio.wait_for(poll(args), timeout=5)
        assert first["status"] == "awaiting_download_approval"
        assert first["artifact"]["sha256"] == image_assets.ENGINE.sha256
        assert "approval_sha256" not in first["artifact"]
        await server.call_tool("image_resume", args)
        assert (await asyncio.wait_for(poll(args), timeout=5))["artifact"] == first["artifact"]

        installed.add(image_assets.ENGINE)
        await server.call_tool("image_resume", args)
        second = await asyncio.wait_for(poll(args), timeout=5)
        assert second["status"] == "awaiting_download_approval"
        assert second["artifact"]["sha256"] == image_assets.MODEL.sha256
        pending = await server.call_tool("image_result", args)
        assert all(item.type == "text" for item in pending.content)

        installed.add(image_assets.MODEL)
        await server.call_tool("image_resume", args)
        verdict = await asyncio.wait_for(poll(args), timeout=5)
        assert verdict["status"] == "passed"
        output = await server.call_tool("image_result", args)
        assert output.structured_content == verdict
        assert output.content[1].mime_type == "image/png"
        assert b64decode(output.content[1].data, validate=True) == png
        with pytest.raises(ToolError, match="n’attend pas"):
            await server.call_tool("image_resume", args)

        corrupt = True
        args = (await server.call_tool("image_start", {"prompt": "Selfie de chat"})).structured_content
        args = {"task_id": args["task_id"]}
        assert (await asyncio.wait_for(poll(args), timeout=5))["status"] == "failed"
        output = await server.call_tool("image_result", args)
        assert all(item.type == "text" for item in output.content)

    asyncio.run(check())


def test_image_cli_prepare_requires_separate_interactive_agreements(tmp_path, monkeypatch):
    from io import StringIO

    class Terminal(StringIO):
        def isatty(self):
            return True

    installed = []

    def discover(cache, runtime):
        for artifact in (image_assets.ENGINE, image_assets.MODEL):
            if artifact not in installed:
                return image_assets.review_download(cache, artifact)
        return None

    def download(review, receipt, checkpoint):
        assert receipt == review.approval_sha256
        installed.append(review.artifact)

    monkeypatch.setattr(image_cli, "discover", discover)
    monkeypatch.setattr(image_cli, "download", download)
    monkeypatch.setattr(image_cli.sys, "stdin", StringIO("oui\noui\n"))
    with pytest.raises(ProjectError, match="terminal interactif"):
        image_cli.prepare_assets(tmp_path)
    assert installed == []

    monkeypatch.setattr(image_cli.sys, "stdin", Terminal("oui\nN\n"))
    with pytest.raises(ProjectError, match="non autorisé"):
        image_cli.prepare_assets(tmp_path)
    assert installed == [image_assets.ENGINE]

    monkeypatch.setattr(image_cli.sys, "stdin", Terminal("oui\n"))
    assert image_cli.prepare_assets(tmp_path)["status"] == "ready"
    assert installed == [image_assets.ENGINE, image_assets.MODEL]


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
