"""Préparation des propositions du parcours Notes sur Rbitnet CPU."""

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

from bench.run_guided_repair import CHECKPOINTS, feedback_prompt, file_hash, infer, model_ram_limit, propose_change
from contracts.akasha_contracts.errors import AkashaError, ErrorCode

from .model_resources import DEFAULT_RAM_MIB, DEFAULT_VRAM_MIB, reserve_model
from .planning import PlanningError

PROMPT_FILE = Path(__file__).with_name("prompts") / "notes-repair-v1.json"
CUDA_LIBRARY_SHA256 = "6cdcfaf0b3ac5fb5a728635b5bb64d78135d7ff0acb467839479288f974f9f9a"


def load_repair_prompt() -> dict:
    prompt = json.loads(PROMPT_FILE.read_text(encoding="utf-8"))
    text = prompt["instructions"] + prompt["requirements"]
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != prompt["sha256"]:
        raise RuntimeError("L'empreinte de la consigne Notes diffère de la version figée.")
    return {**prompt, "text": text}


@dataclass(frozen=True)
class RbitnetPaths:
    engine: Path
    model: Path
    tokenizer: Path
    cuda_library: Path | None = None
    vram_mib: int = DEFAULT_VRAM_MIB
    model_ram_mib: int = DEFAULT_RAM_MIB

    def __post_init__(self):
        if self.cuda_library is not None and self.vram_mib <= 0:
            raise ValueError("CUDA exige un budget de VRAM positif.")

    @property
    def backend(self):
        return "cuda" if self.cuda_library is not None else "cpu"

    def verify(self) -> dict:
        try:
            observed = {name: file_hash(getattr(self, name)) for name in CHECKPOINTS}
            if self.cuda_library is not None:
                observed["cuda_library"] = file_hash(self.cuda_library)
        except OSError as exc:
            raise PlanningError(AkashaError(
                ErrorCode.CAPABILITY_UNAVAILABLE, "Un artefact local Rbitnet est indisponible.",
            )) from exc
        expected = {**CHECKPOINTS, "cuda_library": CUDA_LIBRARY_SHA256} if self.cuda_library is not None else CHECKPOINTS
        if observed != expected:
            raise PlanningError(AkashaError(
                ErrorCode.CAPABILITY_ENGINE_UNSUPPORTED, "Les artefacts Rbitnet diffèrent du protocole évalué.",
            ))
        return observed


def stage_git(stage: Path) -> dict:
    result = subprocess.run(["git", "--exec-path"], capture_output=True, text=True, check=True, timeout=10)
    native = Path(result.stdout.strip()).parents[1] / "bin"
    binary = native / "git.exe"
    if not binary.is_file():
        raise RuntimeError("Git for Windows est requis pour contrôler le diff dans le bac.")
    staged = stage / "git"
    staged.mkdir()
    for path in [binary, *native.glob("*.dll")]:
        shutil.copyfile(path, staged / path.name)
    version = subprocess.run([str(binary), "--version"], capture_output=True, text=True, check=True, timeout=10)
    return {"version": version.stdout.strip(), "sha256": file_hash(binary)}


def generate_patch(paths: RbitnetPaths, work: Path, stage: Path, source: str, prompt: str, seed: int) -> dict:
    work.mkdir()
    (work / "prompt.txt").write_text(prompt, encoding="utf-8")
    with reserve_model("rbitnet", model_ram_limit(paths), vram_mib=paths.vram_mib if paths.cuda_library else 0) as residency:
        response, startup_s, generation_s = infer(paths, work, prompt, seed)
    (work / "model-response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
    choice = response["choices"][0]
    result = {"seed": seed, "startup_s": round(startup_s, 3), "generation_s": round(generation_s, 3),
              "finish_reason": choice.get("finish_reason"), "diff_applied": False, "residency": residency}
    try:
        diff, candidate = propose_change(source, choice["message"].get("content") or "")
        if not diff:
            raise ValueError("Diff vide.")
    except (SyntaxError, ValueError) as exc:
        result["diff_detail"] = str(exc)
        return result

    patch = work / "proposal.diff"
    patch.write_bytes(diff.encode("utf-8"))
    (work / "notes_store.py").write_bytes(candidate.encode("utf-8"))
    mounted = stage / work.name
    mounted.mkdir()
    shutil.copyfile(patch, mounted / patch.name)
    (mounted / "notes-store.sha256").write_text(
        hashlib.sha256(candidate.encode("utf-8")).hexdigest(), encoding="ascii",
    )
    result["diff_file"] = f"{work.name}/{patch.name}"
    result["diff_sha256"] = file_hash(patch)
    return result


def retry_prompt(proposal: dict, validation: dict | None, work: Path, source: str, requirements: str) -> str:
    if validation is None:
        return feedback_prompt(proposal, work, source) + "\n" + requirements
    checks = {
        "passed": validation["passed"],
        "tests": len(validation["tests"]),
        "failures": sum(test["status"] == "failed" for test in validation["tests"]),
        "errors": sum(test["status"] == "error" for test in validation["tests"]),
        "diagnosis": validation["diagnosis"],
        "verifier_exit": validation["sqlite_verifier_exit"],
    }
    return feedback_prompt({**proposal, "validation": checks}, work, source) + "\n" + requirements
