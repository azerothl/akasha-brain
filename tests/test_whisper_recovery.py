from contextlib import nullcontext
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import os
from zipfile import ZipFile

import pytest

from akasha_brain import image_assets as assets, whisper_pilot as pilot, whisper_recovery as recovery
from akasha_brain.project_common import ProjectError


@pytest.mark.skipif(os.name != "nt", reason="Configuration du bureau Windows")
def test_windows_exposes_audio_before_cache_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "app_directory", lambda: tmp_path)
    monkeypatch.delenv("AKASHA_WHISPER_CACHE", raising=False)
    assert pilot.configured() and pilot.cache_path() == tmp_path/"whisper-small"
    assert not pilot.cache_path().exists()
    (tmp_path/"whisper-cache.txt").write_text(str(tmp_path/"existing"), "utf-8")
    assert pilot.cache_path() == tmp_path/"existing"


@pytest.fixture
def installation(tmp_path, monkeypatch):
    archive = BytesIO()
    with ZipFile(archive, "w") as out:
        out.writestr("Release/whisper-cli.exe", b"cli")
    files = {assets.WHISPER_ENGINE.url: archive.getvalue(), assets.WHISPER_MODEL.url: b"model"}
    for name in ("WHISPER_ENGINE", "WHISPER_MODEL"):
        item = getattr(assets, name)
        raw = files[item.url]
        monkeypatch.setattr(assets, name, replace(item, size=len(raw), sha256=sha256(raw).hexdigest()))
    monkeypatch.setattr(pilot, "HASHES", {"whisper-cli.exe": sha256(b"cli").hexdigest(),
                                        "ggml-small.bin": assets.WHISPER_MODEL.sha256})
    monkeypatch.setattr(recovery, "reserve_model", lambda *args: nullcontext())
    calls = []

    class Source:
        def open(self, url, timeout):
            calls.append(url)
            response = BytesIO(files[url])
            response.status = 200
            return response

    monkeypatch.setattr(assets, "build_opener", lambda _: Source())
    return tmp_path/"cache", files, calls


def test_denied_second_download_can_resume_then_reuse(installation, monkeypatch):
    cache, files, requests = installation
    prompts, probes = [], []

    def approve(review):
        prompts.append(review.artifact)
        return "decline" if len(prompts) == 2 else "accept"

    def probe(*args):
        probes.append(args[3])
        return [{"text": "Plages et deux ports dans trois zones."}]

    monkeypatch.setattr(pilot, "cpu_transcribe", probe)
    prepare = lambda: recovery.prepare(cache, lambda: None, approve, lambda _: None)
    with pytest.raises(ProjectError, match="refusé"):
        prepare()
    assert not (cache/assets.WHISPER_MODEL.filename).exists() and not probes
    prepare()
    prepare()
    assert prompts == [assets.WHISPER_ENGINE, assets.WHISPER_MODEL, assets.WHISPER_MODEL]
    assert requests == list(files) and probes == [11160]
    assert len(list(cache.glob("approvals/*/receipt.json"))) == 2
    # Une ancienne preuve ne valide ni des poids corrompus ni un rejeu muet.
    (cache/assets.WHISPER_MODEL.filename).write_bytes(b"altered")
    monkeypatch.setattr(pilot, "cpu_transcribe", lambda *a: [])
    with pytest.raises(ProjectError, match="phrase de qualification"):
        prepare()
    assert requests[-1] == assets.WHISPER_MODEL.url
    assert not (cache/"qualification-whisper-small.json").exists()


def test_cancel_during_transfer_discards_partial_and_spends_consent(installation):
    cache, _, calls = installation
    cache.mkdir()
    review = assets.review_download(cache, assets.WHISPER_MODEL)

    def interrupt():
        if calls:
            raise InterruptedError("annulé")

    with pytest.raises(InterruptedError):
        assets.download(review, review.approval_sha256, interrupt)
    assert not list(cache.glob("*.partial")) and not (cache/review.artifact.filename).exists()
    assert not (review.audit/"receipt.json").exists()
    with pytest.raises(ProjectError, match="déjà servi"):
        assets.download(review, review.approval_sha256, lambda: None)


def test_bad_download_stops_before_qualification(installation, monkeypatch):
    cache, files, _ = installation
    files[assets.WHISPER_MODEL.url] = b"wrong"
    monkeypatch.setattr(pilot, "cpu_transcribe", lambda *a: pytest.fail("unexpected inference"))
    with pytest.raises(ProjectError, match="SHA-256"):
        recovery.prepare(cache, lambda: None, lambda _: "accept", lambda _: None)
    assert not list(cache.glob("*.partial"))
    assert not (cache/"qualification-whisper-small.json").exists()


def test_refuses_cache_in_project_before_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, "cache_path", lambda: tmp_path/"cache")
    with pytest.raises(ProjectError, match="hors du projet"):
        pilot.transcribe(tmp_path, "audio.wav", ask=lambda _: pytest.fail("unexpected approval"))
    assert not list(tmp_path.iterdir())


def test_project_replaced_while_waiting_for_consent(tmp_path, installation, monkeypatch):
    cache, _, calls = installation
    project = tmp_path/"project"
    project.mkdir()
    (project/"audio.wav").write_bytes(recovery.PROBE.read_bytes())
    monkeypatch.setattr(pilot, "cache_path", lambda: cache)

    def switch(_):
        project.rename(tmp_path/"previous")
        project.mkdir()
        return "accept"

    with pytest.raises(ProjectError, match="dossier de projet a changé"):
        pilot.transcribe(project, "audio.wav", ask=switch)
    assert not calls


def test_second_preparation_cannot_spend_first_consent(installation):
    cache, _, calls = installation

    def concurrent(_):
        with pytest.raises(ProjectError, match="déjà en cours"):
            recovery.prepare(cache, lambda: None, lambda _: pytest.fail("unexpected approval"), lambda _: None)
        return "decline"

    with pytest.raises(ProjectError, match="refusé"):
        recovery.prepare(cache, lambda: None, concurrent, lambda _: None)
    assert not calls
