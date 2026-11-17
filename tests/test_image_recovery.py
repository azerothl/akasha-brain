from base64 import b64encode
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from akasha_brain import image_assets, image_recovery, image_windows
from akasha_brain.capability_recovery import Recovery
from akasha_brain.image_execution import validate_export
from akasha_brain.image_linux import CONTROLS, LinuxImageBackend
from akasha_brain.image_windows import WindowsImageBackend, decode_export
from akasha_brain.notes_sandbox import CHANNELS
from akasha_brain.project_common import ProjectError
from contracts.akasha_contracts.errors import ErrorCode


def test_each_artifact_requires_its_own_agreement_and_replays_the_original_prompt(tmp_path, monkeypatch):
    contents = (b"archive", b"weights")
    artifacts = tuple(replace(item, size=len(data), sha256=sha256(data).hexdigest())
                      for item, data in zip(image_assets.ARTIFACTS, contents))
    monkeypatch.setattr(image_assets, "ARTIFACTS", artifacts)
    calls, prompts = [], []
    backend = SimpleNamespace(tier="windows-sandbox", label="Windows Sandbox", verifies=WindowsImageBackend.verifies)

    def fetch(url, **_):
        calls.append(url)
        response = BytesIO(dict(zip((item.url for item in artifacts), contents))[url])
        response.status = 200
        return response

    def discover(cache, runtime):
        for artifact in artifacts:
            if not image_assets.matches(cache / artifact.filename, artifact):
                return image_assets.review_download(cache, artifact)
        return SimpleNamespace(fingerprint="verified-assets", backend=backend)

    def generate(candidate, prompt, checkpoint):
        prompts.append(prompt)
        return image_recovery.ImageResult(b"rendered", {
            "status": "passed", "sandbox_stopped": True, "read_only_input": True,
                "guest_exit_code": 0, "mount_probe": 0x450F, "channel_probe": 0x411F, "disabled_channels": list(CHANNELS),
                "headless": True, "export_transport": "hcs-stdout",
            "backend": "windows-sandbox", "candidate_sha256": candidate.fingerprint, "png": {},
        })

    monkeypatch.setattr(image_assets, "build_opener", lambda *_: SimpleNamespace(open=fetch))
    monkeypatch.setattr(image_recovery, "discover", discover)
    monkeypatch.setattr(image_recovery, "run", generate)
    recovery = Recovery(tmp_path / "recovery.sqlite", None, lambda _: None, lambda: False)
    prompt = "un chat faisant un selfie devant un miroir"
    first = recovery.generate_image(prompt, None, None)
    assert first.artifact == artifacts[0] and calls == prompts == []
    with pytest.raises(ProjectError) as missing:
        image_assets.download(first, None, lambda: None)
    assert missing.value.error.code == ErrorCode.APPROVAL_REQUIRED and not calls

    model = recovery.generate_image(prompt, None, (first, first.approval_sha256))
    assert model.artifact == artifacts[1] and calls == [first.artifact.url] and not prompts
    with pytest.raises(ProjectError) as wrong:
        image_assets.download(model, first.approval_sha256, lambda: None)
    assert wrong.value.error.code == ErrorCode.APPROVAL_REQUIRED and len(calls) == 1

    result = recovery.generate_image(prompt, None, (model, model.approval_sha256))
    assert result.png == b"rendered" and calls == [item.url for item in artifacts]
    assert prompts == [image_recovery.QUALIFICATION, prompt]
    with pytest.raises(ProjectError):
        image_assets.download(model, model.approval_sha256, lambda: None)
    recovery.generate_image(prompt, None, None)
    assert prompts == [image_recovery.QUALIFICATION, prompt, prompt] and len(calls) == 2


def test_windows_export_requires_exact_size_and_checksum():
    raw = bytes(range(256))
    record = {"bytes": len(raw), "sha256": sha256(raw).hexdigest(), "data": b64encode(raw).decode("ascii")}
    assert decode_export(json.dumps(record).encode()) == raw
    for corrupt in ({"bytes": len(raw) + 1}, {"sha256": "0" * 64}, {"data": record["data"] + "!"}):
        with pytest.raises(ProjectError) as error:
            decode_export(json.dumps({**record, **corrupt}).encode())
        assert error.value.error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED


@pytest.mark.parametrize("channel_code", [0x410F, 0x411F])
def test_windows_requires_isolation_and_a_verified_hcs_peer(tmp_path, monkeypatch, channel_code):
    active, commands = [], []

    def wsb(action, *_args):
        commands.append(action)
        if action == "start":
            active.append(_args[1])
            return {"Id": active[0]}
        if action == "share":
            assert "--allow-write" not in _args
        if action == "stop":
            active.clear()

    def guest_exit(_sandbox, command):
        if command.endswith("exit 0"):
            return 0
        return 0x450F if "isolation" in command else channel_code

    def wrong_peer(_tool, args, *_other):
        assert channel_code == 0x411F and args[-2] == "type"
        return b"unrelated-sandbox"

    monkeypatch.setattr(image_windows, "wsb", wsb)
    monkeypatch.setattr(image_windows, "active_sandboxes", lambda: list(active))
    monkeypatch.setattr(image_windows, "assert_headless", lambda _: None)
    monkeypatch.setattr(image_windows, "compute_ids", lambda _: {"compute-id"} if active else set())
    monkeypatch.setattr(image_windows, "system_guest_exit", guest_exit)
    monkeypatch.setattr(image_windows, "tool_stdout", wrong_peer)
    with pytest.raises(ProjectError) as error:
        image_windows.execute_headless(tmp_path, lambda: None)
    assert error.value.error.code == ErrorCode.PERMISSION_DENIED
    assert commands == ["start", "share", "stop"] and active == []


def test_linux_rejects_missing_isolation_controls():
    proof = {"status": "passed", "sandbox_stopped": True, "guest_exit_code": 0,
             "isolation": dict.fromkeys(CONTROLS, True)}
    assert LinuxImageBackend.verifies(proof)
    for key in CONTROLS:
        assert not LinuxImageBackend.verifies({**proof, "isolation": {**proof["isolation"], key: False}})


def test_export_verifies_the_file_and_removes_private_metadata():
    image = Image.new("RGB", (512, 512))
    draw = ImageDraw.Draw(image)
    for x in range(32):
        draw.rectangle((x * 16, 0, x * 16 + 15, 511), fill=(7 * x, 40, 150))
    output = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("prompt", "private")
    image.save(output, format="PNG", pnginfo=metadata)
    raw = output.getvalue()
    validated, receipt = validate_export(raw)
    with Image.open(BytesIO(validated)) as exported:
        assert exported.size == (512, 512) and "prompt" not in exported.info
    assert receipt["input_sha256"] == sha256(raw).hexdigest()
    assert receipt["sha256"] == sha256(validated).hexdigest()
    with pytest.raises(ProjectError) as corrupt:
        validate_export(raw[:100])
    assert corrupt.value.error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED
