"""Demandes unitaires, téléchargement approuvé et cache de wheels vérifiées."""

from email import policy
from email.parser import BytesParser
from importlib.metadata import PackageNotFoundError, distribution
import json
from pathlib import Path
import re
import shutil
from urllib.error import URLError
from urllib.parse import unquote, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from bench.run_guided_repair import file_hash
from contracts.akasha_contracts.authz import authorize
from contracts.akasha_contracts.errors import ErrorCode

from .project_common import ProjectError, digest, identity, reject


def dependency_fields(name: str, version: str, url: str, sha256: str, license: str) -> dict:
    source = urlsplit(url)
    loopback = source.scheme == "http" and source.hostname in ("127.0.0.1", "::1")
    if (not (source.scheme == "https" or loopback) or not source.hostname or source.username is not None
            or source.fragment or any(char.isspace() or ord(char) < 32 for char in url)):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Une URL directe HTTPS ou HTTP sur loopback est requise.")
    filename = unquote(source.path.rsplit("/", 1)[-1])
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+\-]*\.whl", filename):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'URL doit désigner une wheel Python.")
    if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version)
            or not re.fullmatch(r"[a-fA-F0-9]{64}", sha256)
            or not license.strip() or any(ord(char) < 32 for char in license)):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Nom, version, SHA-256 et licence exacts sont requis.")
    return {"name": name, "version": version, "url": url, "filename": filename,
            "sha256": sha256.lower(), "license": license.strip()}


def dependency_directory(project: Path, directory: Path) -> Path:
    directory = directory.resolve()
    if directory.is_relative_to(project):
        reject(ErrorCode.PERMISSION_DENIED, "Stocker la demande et le cache hors du projet.")
    return directory


def create_request(project: Path, output: Path, *, name: str, version: str, url: str, sha256: str, license: str) -> dict:
    project = project.resolve(strict=True)
    output = dependency_directory(project, output)
    dependency = dependency_fields(name, version, url, sha256, license)
    request = {"request_id": str(uuid4()), "project": identity(project), "directory": str(output),
               "dependency": dependency}
    encoded = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.mkdir(parents=True)
    (output / "request.json").write_bytes(encoded)
    return {"status": "awaiting_download_approval", "request": str(output),
            "approval_sha256": digest(encoded), "dependency": dependency}


def read_request(project: Path, directory: Path) -> tuple[dict, str]:
    encoded = (directory / "request.json").read_bytes()
    request = json.loads(encoded)
    entry = request["dependency"]
    dependency = dependency_fields(entry["name"], entry["version"], entry["url"], entry["sha256"], entry["license"])
    if identity(project) != request["project"] or str(directory) != request["directory"] or dependency != entry:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "La demande ne correspond pas au projet ou à l'artefact.")
    return dependency, digest(encoded)


def normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def verify_wheel(path: Path, dependency: dict) -> None:
    if file_hash(path) != dependency["sha256"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "L'empreinte de la wheel diffère de la demande.",
               reason="dependency_hash_mismatch")
    try:
        with ZipFile(path) as wheel:
            entries = [file for file in wheel.namelist() if re.fullmatch(r"[^/]+\.dist-info/METADATA", file)]
            if len(entries) != 1:
                reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Métadonnées de wheel ambiguës ou absentes.")
            metadata = BytesParser(policy=policy.default).parsebytes(wheel.read(entries[0]), headersonly=True)
    except BadZipFile:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Archive wheel invalide.")
    if (normalized_name(metadata.get("Name", "")) != normalized_name(dependency["name"])
            or metadata.get("Version") != dependency["version"]):
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Nom ou version de la wheel non conforme.")
    if (metadata.get("License-Expression") or metadata.get("License")) != dependency["license"]:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Licence déclarée par la wheel différente de la demande.",
               reason="dependency_license_mismatch")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(project: Path, request: Path, approval: str | None) -> dict:
    project = project.resolve(strict=True)
    request = dependency_directory(project, request)
    dependency, request_hash = read_request(project, request)
    denied = authorize({"risk_class": "R3", "human_approval": approval == request_hash})
    if denied:
        raise ProjectError(denied)

    cache = request / "cache"
    try:
        with (request / "download.claim").open("x", encoding="ascii") as claim:
            claim.write(request_hash + "\n")
    except FileExistsError:
        reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Demande déjà utilisée. Une nouvelle demande est requise pour télécharger.",
               reason="download_already_requested")
    cache.mkdir()
    partial = cache / "download.partial"
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        with opener.open(dependency["url"], timeout=30) as response, partial.open("xb") as output:
            if response.status != 200:
                reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "La source n'a pas fourni une réponse complète.")
            shutil.copyfileobj(response, output)
        verify_wheel(partial, dependency)
        partial.rename(cache / dependency["filename"])
        receipt = {"status": "downloaded", "request_sha256": request_hash, "dependency": dependency}
        (cache / "receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    except URLError:
        reject(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED, "Téléchargement impossible depuis la source approuvée.")
    finally:
        partial.unlink(missing_ok=True)
    return receipt


def stage_dependencies(project: Path, requests, stage: Path) -> list[dict]:
    staged = []
    names = set()
    if requests:
        (stage / "wheels").mkdir()
    for directory in requests:
        request = dependency_directory(project, directory)
        dependency, request_hash = read_request(project, request)
        cache = request / "cache"
        receipt = {"status": "downloaded", "request_sha256": request_hash, "dependency": dependency}
        receipt_path = cache / "receipt.json"
        if not receipt_path.is_file() or json.loads(receipt_path.read_bytes()) != receipt:
            reject(ErrorCode.APPROVAL_REQUIRED, "Chaque wheel doit provenir d'une demande téléchargée et vérifiée.")
        name = normalized_name(dependency["name"])
        destination = stage / "wheels" / dependency["filename"]
        if name in names or destination.exists():
            reject(ErrorCode.CONTRACT_PRECONDITION_FAILED, "Plusieurs wheels couvrent la même dépendance ou le même fichier.")
        shutil.copyfile(cache / dependency["filename"], destination)
        verify_wheel(destination, dependency)
        names.add(name)
        staged.append({**dependency, "request_sha256": request_hash})
    return staged


def stage_installer(stage: Path) -> str:
    try:
        pip = distribution("pip")
    except PackageNotFoundError:
        reject(ErrorCode.CAPABILITY_UNAVAILABLE, "Le lanceur local requiert une installation existante de pip.")
    shutil.copytree(pip.locate_file("pip"), stage / "installer" / "pip", ignore=shutil.ignore_patterns("__pycache__"))
    return pip.version
