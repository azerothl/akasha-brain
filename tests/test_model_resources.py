import subprocess
import sys

import pytest

from akasha_brain import model_resources
from akasha_brain.planning import PlanningError
from contracts.akasha_contracts.errors import ErrorCode


@pytest.fixture
def model_memory(monkeypatch):
    monkeypatch.setenv("AKASHA_RAM_LIMIT_MIB", "8192")
    monkeypatch.setenv("AKASHA_VRAM_LIMIT_MIB", "4096")
    monkeypatch.setattr(model_resources, "available_ram", lambda: 10000)
    monkeypatch.setattr(model_resources, "available_vram", lambda: 3072)


@pytest.mark.parametrize("ram,vram,reason", [(8193, 0, "ram_budget"), (8192, 3073, "vram_budget")])
def test_admission_respects_host_memory_and_configured_limits(model_memory, ram, vram, reason):
    with pytest.raises(PlanningError) as seen:
        with model_resources.reserve_model("rbitnet", ram, vram_mib=vram):
            pytest.fail("The model was admitted above the available budget")
    assert seen.value.error.code == ErrorCode.RESIDENCY_UNAVAILABLE
    assert seen.value.error.details["reason"] == reason
    with model_resources.reserve_model("rbitnet", 8192, vram_mib=3072) as report:
        assert report["device_vram_free_mib"] == 3072
    assert report["lease_s"] >= 0


@pytest.mark.skipif(sys.platform != "win32", reason="Le bail interprocessus utilise le mutex Windows.")
def test_windows_releases_the_shared_lease_after_failure(model_memory):
    script = """from akasha_brain.model_resources import reserve_model
from akasha_brain.planning import PlanningError
try:
    with reserve_model('onnxruntime', 1, inside_sandbox=True):
        print('admitted')
except PlanningError as error:
    print(error.error.details['reason'])
"""

    def other_process():
        return subprocess.check_output([sys.executable, "-X", "utf8", "-B", "-c", script],
                                       encoding="utf-8", timeout=5).strip()

    with pytest.raises(RuntimeError, match="load failed"):
        with model_resources.reserve_model("rbitnet", 4096):
            assert other_process() == "inference_busy"
            raise RuntimeError("load failed")
    assert other_process() == "admitted"
