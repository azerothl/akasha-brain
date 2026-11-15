from io import BytesIO
from zipfile import ZipFile

import pytest

from akasha_brain import project_dependencies as dependencies
from akasha_brain.project_common import ProjectError, digest
from contracts.akasha_contracts.errors import ErrorCode


@pytest.fixture
def dependency_request(tmp_path, monkeypatch):
    content = BytesIO()
    with ZipFile(content, "w") as wheel:
        wheel.writestr("sample-1.2.dist-info/METADATA",
                       "Metadata-Version: 2.4\nName: sample\nVersion: 1.2\nLicense-Expression: MIT\n\n")
    payload = content.getvalue()
    project = tmp_path / "project"
    project.mkdir()
    filename = "sample-1.2-py3-none-any.whl"
    options = {"name": "sample", "version": "1.2", "url": f"https://packages.example.invalid/{filename}",
               "sha256": digest(payload), "license": "MIT"}
    directory = tmp_path / "request"
    request = dependencies.create_request(project, directory, **options)
    hits = []

    class Opener:
        def open(self, url, *, timeout):
            hits.append(url)
            response = BytesIO(payload)
            response.status = 200
            return response

    monkeypatch.setattr(dependencies, "build_opener", lambda *handlers: Opener())
    return project, directory, request["approval_sha256"], options, filename, hits


def test_refuses_download_before_contacting_source(dependency_request, tmp_path):
    project, directory, approval, options, _, hits = dependency_request
    other = tmp_path / "new_request"
    dependencies.create_request(project, other, **options)
    for request, provided in ((directory, None), (other, approval)):
        with pytest.raises(ProjectError) as error:
            dependencies.download(project, request, provided)
        assert error.value.error.code == ErrorCode.APPROVAL_REQUIRED
        assert not (request / "cache").exists()
    assert hits == []


def test_download_is_single_use_and_only_verified_cache_is_staged(dependency_request, tmp_path):
    project, directory, approval, options, filename, hits = dependency_request
    result = dependencies.download(project, directory, approval)
    assert result["status"] == "downloaded"
    with pytest.raises(ProjectError) as error:
        dependencies.download(project, directory, approval)
    assert error.value.error.details["reason"] == "download_already_requested"
    assert hits == [options["url"]]

    stage = tmp_path / "stage"
    stage.mkdir()
    staged, = dependencies.stage_dependencies(project, [directory], stage)
    assert staged["request_sha256"] == approval
    assert digest((stage / "wheels" / filename).read_bytes()) == options["sha256"]

    (directory / "cache" / filename).write_bytes(b"tampered")
    fresh_stage = tmp_path / "fresh-stage"
    fresh_stage.mkdir()
    with pytest.raises(ProjectError) as error:
        dependencies.stage_dependencies(project, [directory], fresh_stage)
    assert error.value.error.details["reason"] == "dependency_hash_mismatch"


def test_rejects_license_mismatch_without_publishing_cache(dependency_request, tmp_path):
    project, _, _, options, filename, hits = dependency_request
    directory = tmp_path / "wrong-license"
    request = dependencies.create_request(project, directory, **{**options, "license": "Apache-2.0"})
    with pytest.raises(ProjectError) as error:
        dependencies.download(project, directory, request["approval_sha256"])
    assert error.value.error.details["reason"] == "dependency_license_mismatch"
    assert not (directory / "cache" / filename).exists()
    assert not (directory / "cache" / "receipt.json").exists()
    assert hits == [options["url"]]
