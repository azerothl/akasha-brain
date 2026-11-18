"""Acquisition consentie et qualification locale du profil de base Whisper small."""

from hashlib import sha256
import json
from pathlib import Path
import platform
import shutil
import sqlite3
from tempfile import TemporaryDirectory, NamedTemporaryFile
from zipfile import ZipFile

from bench.run_guided_repair import BENCH, file_hash
from contracts.akasha_contracts.errors import ErrorCode
from . import image_assets as assets
from .model_resources import reserve_model
from .experience import transaction
from .project_common import reject

PROBE = BENCH/"corpora/g7-fr-v1/14203199903136889342.wav"
PROBE_HASH = "599129646540b2c196ec37144db546448de97981ed9d9d19f068e3b136cfabb9"
EXPECTED = ("plages", "deux ports", "trois zones")


def describe(review):
    item = review.artifact
    return (f"Autoriser le téléchargement de {item.name} ({item.size:,} octets) ?\n"
            f"Version {item.version}\n{item.url}\nLicence {item.license} · {item.license_url}\n"
            f"SHA-256 {item.sha256}")


def obtain(cache, item, ask, checkpoint):
    path = cache/item.filename
    if not assets.matches(path, item):
        review = assets.review_download(cache, item)
        if ask is None:
            reject(ErrorCode.APPROVAL_REQUIRED, describe(review))
        decision = ask(review)
        checkpoint()
        if decision == "cancel":
            raise InterruptedError("Transcription annulée.")
        if decision != "accept":
            reject(ErrorCode.PERMISSION_DENIED, "Téléchargement refusé. La transcription a été arrêtée.")
        assets.download(review, review.approval_sha256, checkpoint)
    return path


def install_engine(cache, binaries, ask, checkpoint):
    if all(path.is_file() and file_hash(path) == expected for path, expected in binaries.items()):
        return
    archive = obtain(cache, assets.WHISPER_ENGINE, ask, checkpoint)
    with TemporaryDirectory(dir=cache) as tmp, ZipFile(archive) as bundle:
        for path, expected in binaries.items():
            checkpoint()
            target = Path(tmp)/path.name
            with bundle.open("Release/"+path.name) as source, target.open("wb") as out:
                shutil.copyfileobj(source, out)
            if file_hash(target) != expected:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Binaire Whisper non conforme.", artifact=path.name)
        checkpoint()
        for path in binaries:
            path.parent.mkdir(parents=True, exist_ok=True)
            (Path(tmp)/path.name).replace(path)


def signature(files, hashes):
    try:
        stamps = []
        for path in files:
            stat = path.stat()
            stamps.append([path.name, stat.st_ino, stat.st_size, stat.st_mtime_ns])
    except FileNotFoundError:
        return None
    return {"artifacts": hashes, "files": stamps, "host": [platform.node(), platform.version(), platform.machine()],
            "probe": PROBE_HASH, "qualification": file_hash(Path(__file__)),
            "adapter": file_hash(Path(__file__).with_name("whisper_pilot.py")),
            "guest": file_hash(BENCH/"harness/whisper_guest.ps1")}


def prepare(cache, checkpoint, ask, progress):
    from . import whisper_pilot as pilot

    binaries = {cache/"whisper/Release"/name: expected for name, expected in pilot.HASHES.items()
                if name != assets.WHISPER_MODEL.filename}
    model = cache/assets.WHISPER_MODEL.filename
    receipt = cache/"qualification-whisper-small.json"
    for path in (*binaries, model, receipt, cache/assets.WHISPER_ENGINE.filename, cache/"approvals",
                 cache/"approvals/akasha-audit.sqlite", cache/"qualification.lease.db"):
        if path.resolve() != path:
            reject(ErrorCode.PERMISSION_DENIED, "Lien interdit dans le cache Whisper.")

    def qualified():
        try:
            saved = json.loads(receipt.read_bytes())
        except (FileNotFoundError, ValueError):
            return False
        current = signature((*binaries, model), pilot.HASHES)
        return (current is not None and isinstance(saved, dict) and saved.get("signature") == current
                and saved.get("matched") == list(EXPECTED))

    checkpoint()
    if qualified():
        return
    cache.mkdir(parents=True, exist_ok=True)
    with transaction(cache/"qualification.lease.db") as db:
        db.execute("PRAGMA busy_timeout = 0")
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise
            reject(ErrorCode.RESOURCE_BUDGET_EXCEEDED, "Une préparation du cache Whisper est déjà en cours.")
        if qualified():
            return
        receipt.unlink(missing_ok=True)
        install_engine(cache, binaries, ask, checkpoint)
        obtain(cache, assets.WHISPER_MODEL, ask, checkpoint)
        checkpoint()
        progress("Je vérifie Whisper sur une phrase française de référence.")
        raw = PROBE.read_bytes()
        if sha256(raw).hexdigest() != PROBE_HASH:
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L’extrait de qualification Whisper a changé.")
        duration, _ = pilot.audio_info(raw, ".wav")
        with reserve_model("whisper.cpp-small", pilot.RAM_MIB):
            segments = pilot.cpu_transcribe(cache, raw, ".wav", duration, checkpoint)
        transcript = " ".join(segment["text"].casefold() for segment in segments)
        if not all(word in transcript for word in EXPECTED):
            reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Whisper n’a pas reconnu la phrase de qualification.")
        checkpoint()
        proof = {"signature": signature((*binaries, model), pilot.HASHES), "matched": list(EXPECTED),
                 "device": "cpu", "segments": len(segments)}
        with NamedTemporaryFile(mode="w", encoding="utf8", dir=cache, delete=False) as stream:
            tmp = Path(stream.name)
            json.dump(proof, stream)
        try:
            checkpoint()
            tmp.replace(receipt)
        finally:
            tmp.unlink(missing_ok=True)
        progress("Whisper est qualifié. Je reprends la transcription demandée.")
