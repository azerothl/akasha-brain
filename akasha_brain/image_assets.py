"""Catalogue d'artefacts et accord unitaire pour le moteur d'images."""

from dataclasses import asdict, dataclass
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

from bench.run_guided_repair import file_hash
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .project_approval import new_request, require_fresh
from .project_audit import record
from .project_common import ProjectError, reject


@dataclass(frozen=True)
class Artifact:
    name: str
    version: str
    filename: str
    source: str
    url: str
    sha256: str
    size: int
    license: str
    license_url: str
    redirect_hosts: tuple[str, ...]


ENGINE = Artifact(
    "stable-diffusion.cpp (Windows x64, CPU)", "master-955-b7a74e6",
    "sd-master-b7a74e6-bin-win-cpu-x64.zip",
    "https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-955-b7a74e6",
    "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-955-b7a74e6/"
    "sd-master-b7a74e6-bin-win-cpu-x64.zip",
    "08c6b1015370f10c3ee1e689b42738d6281c910b375aefc755f3b49989e779a1", 17_540_346,
    "MIT", "https://github.com/leejet/stable-diffusion.cpp/blob/b7a74e6/LICENSE",
    ("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"),
)
LINUX_ENGINE = Artifact(
    "stable-diffusion.cpp (Linux x86_64, CPU)", "master-955-b7a74e6",
    "sd-master-b7a74e6-bin-Linux-Ubuntu-24.04-x86_64.zip",
    "https://github.com/leejet/stable-diffusion.cpp/releases/tag/master-955-b7a74e6",
    "https://github.com/leejet/stable-diffusion.cpp/releases/download/master-955-b7a74e6/"
    "sd-master-b7a74e6-bin-Linux-Ubuntu-24.04-x86_64.zip",
    "c33577f8340dc1ac4212adac7def108ecc08e3047d8a3c2d460cc878eac0e78b", 26_122_695,
    "MIT", "https://github.com/leejet/stable-diffusion.cpp/blob/b7a74e6/LICENSE",
    ("github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"),
)
MODEL = Artifact(
    "SD-Turbo Q4_0 (samoudi, dérivé de Stability AI)", "0b5ee51e9a43b33b2d32865781719a85a2248c12",
    "sd_turbo_q4_0.gguf", "https://huggingface.co/samoudi/sd-turbo-gguf",
    "https://huggingface.co/samoudi/sd-turbo-gguf/resolve/0b5ee51e9a43b33b2d32865781719a85a2248c12/"
    "sd_turbo_q4_0.gguf",
    "d069ef2b2d3d5c2465662d706c242a1016db56163c109bd7e3008a94cdd00359", 1_847_909_248,
    "Stability AI Community License", "https://huggingface.co/samoudi/sd-turbo-gguf/blob/"
    "0b5ee51e9a43b33b2d32865781719a85a2248c12/LICENSE.md",
    ("huggingface.co", "us.aws.cdn.hf.co", "cas-bridge.xethub.hf.co", "cdn-lfs.huggingface.co",
     "cdn-lfs-us-1.huggingface.co", "cdn-lfs-eu-1.huggingface.co"),
)
ARTIFACTS = (ENGINE, MODEL)


@dataclass(frozen=True)
class DownloadReview:
    artifact: Artifact
    directory: Path
    request_id: str
    expires_at: str

    @property
    def approval_sha256(self):
        data = [self.request_id, self.expires_at, str(self.directory), asdict(self.artifact)]
        return sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()

    @property
    def audit(self):
        return self.directory / "approvals" / self.request_id


def review_download(cache: Path, artifact: Artifact) -> DownloadReview:
    request = new_request()
    return DownloadReview(artifact, cache.resolve(), request["id"], request["expires_at"])


def matches(path: Path, artifact: Artifact) -> bool:
    return not path.is_symlink() and path.is_file() and path.stat().st_size == artifact.size and file_hash(path) == artifact.sha256


def find_local(cache: Path, artifact: Artifact) -> Path | None:
    return next((path for folder in (cache, Path.home() / "Downloads")
                 if matches(path := folder / artifact.filename, artifact)), None)


class CatalogRedirects(HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme != "https" or target.hostname not in self.hosts
                or target.username is not None or target.port not in (None, 443)):
            reject(ErrorCode.PERMISSION_DENIED, "Redirection hors des hôtes prévus pour cet artefact.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(review: DownloadReview, approval: str | None, checkpoint) -> None:
    artifact = review.artifact
    denied = authorize({"risk_class": "R3", "human_approval": (
        artifact in (*ARTIFACTS, LINUX_ENGINE) and approval == review.approval_sha256
    )})
    if denied:
        raise ProjectError(denied)
    expires = datetime.fromisoformat(review.expires_at)
    require_fresh(expires)
    checkpoint()
    review.audit.mkdir(parents=True, exist_ok=True)
    try:
        with (review.audit / "download.claim").open("x", encoding="ascii") as claim:
            claim.write(review.approval_sha256)
    except FileExistsError:
        reject(ErrorCode.APPROVAL_REQUIRED, "Cet accord a déjà servi. Un nouvel accord est nécessaire.")
    record(review.audit, action="image_artifact_download", risk="R3", actor="human", decision="approved")

    partial = None
    deadline = monotonic() + 900
    try:
        require_fresh(expires)
        opener = build_opener(CatalogRedirects(artifact.redirect_hosts))
        with NamedTemporaryFile(dir=review.directory, suffix=".partial", delete=False) as output:
            partial = Path(output.name)
            digest, size = sha256(), 0
            with opener.open(artifact.url, timeout=30) as response:
                if response.status != 200:
                    reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "La source n’a pas fourni le fichier complet.")
                while chunk := response.read(1024 * 1024):
                    checkpoint()
                    size += len(chunk)
                    if monotonic() > deadline or size > artifact.size:
                        reject(ErrorCode.RESOURCE_BUDGET_EXCEEDED, "Budget de téléchargement dépassé.")
                    digest.update(chunk)
                    output.write(chunk)
            if size != artifact.size or digest.hexdigest() != artifact.sha256:
                reject(ErrorCode.CONTRACT_POSTCONDITION_FAILED, "Taille ou SHA-256 de l’artefact incorrect.")
        checkpoint()
        os.replace(partial, review.directory / artifact.filename)
        (review.audit / "receipt.json").write_text(json.dumps({
            "approval_sha256": review.approval_sha256, "artifact": asdict(artifact),
        }, ensure_ascii=False), encoding="utf-8")
        record(review.audit, action="image_artifact_download", risk="R3", actor="runtime", decision="verified")
    except URLError as error:
        raise ProjectError(AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED,
                           "Téléchargement impossible depuis la source approuvée.")) from error
    finally:
        if partial is not None:
            partial.unlink(missing_ok=True)
