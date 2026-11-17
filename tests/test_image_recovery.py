from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, PngImagePlugin

from akasha_brain import image_assets, image_recovery
from akasha_brain.capability_recovery import Recovery
from akasha_brain.image_execution import validate_export
from akasha_brain.image_linux import CONTROLS, LinuxImageBackend
from akasha_brain.image_preview import crop_frame
from akasha_brain.image_windows import verifies_windows
from akasha_brain.notes_sandbox import CHANNELS
from akasha_brain.project_common import ProjectError
from contracts.akasha_contracts.errors import ErrorCode


def test_each_artifact_requires_its_own_agreement_and_replays_the_original_prompt(tmp_path, monkeypatch):
    contents = (b"archive", b"weights")
    artifacts = tuple(replace(item, size=len(data), sha256=sha256(data).hexdigest())
                      for item, data in zip(image_assets.ARTIFACTS, contents))
    monkeypatch.setattr(image_assets, "ARTIFACTS", artifacts)
    calls, prompts = [], []
    backend = SimpleNamespace(tier="windows-sandbox", label="Windows Sandbox", verifies=verifies_windows)

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
            "guest_exit_code": 0x4700, "channel_probe": 0x410F, "disabled_channels": list(CHANNELS),
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


def test_capture_requires_the_complete_marked_frame():
    frame = "#13f3ba"
    viewport = Image.new("RGB", (800, 700), color="#202020")
    render = Image.new("RGB", (544, 544), color=(20, 238, 184))
    draw = ImageDraw.Draw(render)
    for x in range(32):
        draw.rectangle((16 + x * 16, 16, 31 + x * 16, 527), fill=(7 * x, 20, 150))
    viewport.paste(render, (30, 70))
    cropped = crop_frame(viewport, frame)
    assert cropped.size == (512, 512)
    assert cropped.getpixel((0, 0)) == (0, 20, 150)
    ImageDraw.Draw(viewport).rectangle((35, 320, 42, 400), fill="red")
    assert crop_frame(viewport, frame) is None


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
