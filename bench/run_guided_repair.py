"""Rejeu CPU du parcours de réparation guidée des notes dans Windows Sandbox."""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from contextvars import ContextVar
import difflib
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
from tempfile import TemporaryFile
import textwrap
import time
from urllib import error, request


BENCH = Path(__file__).resolve().parent
SEEDS = ((741, 751), (742, 752), (743, 753))
ATTEMPT_BUDGET = 60
CYCLE_BUDGET = 120
MAX_TOKENS = 176
TEMPERATURE = 0.0
HTTP_TIMEOUT_S = 135
CHECKPOINTS = {
    "engine": "80cd4e7f7c39b1facb4073915253965c60f85fd936d08c242221acb2cae1f49c",
    "model": "120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4",
    "tokenizer": "aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4",
}
FIRST_PROMPT = (
    "/no_think\n"
    "Write a complete Python replacement for this method. Output a single Python code block "
    "and no other text. Keep its signature. self._conn is an open SQLite connection. "
    "Insert title and content into the notes table, make the write durable after closing, "
    "return the database id, and ensure the note is visible exactly once. "
    "list_notes already combines rows from SQLite and the session cache.\n\n"
)
CLOSED_CONNECTION_PROMPT = (
    "/no_think\n"
    "Fix the Python method below. SQLite persistence passed, but the regression suite failed "
    "because save_note closes the connection and prevents subsequent saves or list_notes. "
    "The caller owns the database connection and closes it separately. Keep the committed "
    "INSERT, return the actual new row ID, and keep the connection available for the caller. "
    "Output one fenced Python block containing the complete corrected method with the same signature.\n\n"
)

_deadline = ContextVar("notes_deadline", default=None)
_model_limits = ContextVar("notes_model_limits", default=None)


class ModelAdmissionBudgetExceeded(RuntimeError):
    pass


@contextmanager
def execution_limits(deadline: float | None, cpu_threads: int | None = None, model_ram_mb: int | None = None):
    clock_token = _deadline.set(deadline)
    model_token = _model_limits.set((cpu_threads, model_ram_mb) if cpu_threads is not None else None)
    try:
        yield
    finally:
        _model_limits.reset(model_token)
        _deadline.reset(clock_token)


def bounded_timeout(timeout: float) -> float:
    deadline = _deadline.get()
    if deadline is None:
        return timeout
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Budget de temps du banc Notes épuisé.")
    return min(timeout, remaining)


def model_ram_limit(args) -> int | None:
    limits = _model_limits.get()
    return limits[1] if limits else getattr(args, "model_ram_mib", None)


def file_hash(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def wsb(*args: str) -> dict:
    # Le client démarré par Windows Sandbox peut hériter des flux de la CLI.
    # Des fichiers évitent d'attendre la fermeture de tous les descendants.
    with TemporaryFile() as out, TemporaryFile() as err:
        result = subprocess.run(["wsb.exe", *args, "--raw"], stdout=out, stderr=err, timeout=bounded_timeout(65),
                                creationflags=subprocess.CREATE_NO_WINDOW)
        out.seek(0)
        err.seek(0)
        stdout = out.read().decode("utf-8-sig", errors="replace")
        stderr = err.read().decode("utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"wsb {args[0]} ({result.returncode}): {stdout} {stderr}")
    return json.loads(stdout) if stdout.strip() else {}


def prepare(stage: Path, runtime: Path) -> dict:
    if sys.version_info[:3] != (3, 12, 7) or version("pytest") != "9.2.0":
        raise RuntimeError("Le protocole utilise Python 3.12.7 et pytest 9.2.0.")
    shutil.copytree(runtime, stage / "python")
    fixture = stage / "fixture"
    fixture.mkdir()
    notes = BENCH / "notes"
    for name in ("conftest.py", "notes_app.py"):
        shutil.copy2(notes / name, fixture / name)
    for name in ("tests", "verifiers"):
        shutil.copytree(notes / name, fixture / name, ignore=shutil.ignore_patterns("__pycache__"))
    packages = stage / "packages"
    packages.mkdir()
    site = Path(sys.prefix) / "Lib" / "site-packages"
    for name in ("_pytest", "pytest", "pluggy", "packaging", "iniconfig", "pygments", "colorama"):
        shutil.copytree(site / name, packages / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(site / "py.py", packages)
    shutil.copy2(BENCH / "harness" / "validate_guided_notes.ps1", stage)
    return {str(path.relative_to(fixture)).replace("\\", "/"): file_hash(path)
            for path in sorted(fixture.rglob("*.py"))}


def guest_validate(sandbox_id: str, tag: str, name: str, locate: bool = False) -> dict:
    script = fr"C:\AkashaGuidedInput-{tag}\validate_guided_notes.ps1"
    command = (
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe "
        r"-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass "
        f"-File {script} -Tag {tag} -InputName {name}"
    )
    if locate:
        command += " -Locate"
    code = wsb("exec", "--id", sandbox_id, "--run-as", "ExistingLogin", "--command", command)["ExitCode"]
    if code >> 28 != 4:
        raise RuntimeError(f"Vérification dans le bac interrompue, code {code}.")
    fields = ("diagnosis", "tests", "failures", "errors", "skips", "pytest_exit", "verifier_exit")
    result = {field: (code >> shift) & 15 for field, shift in zip(fields, range(24, -1, -4))}
    result["passed"] = result["tests"] - result["failures"] - result["errors"] - result["skips"]
    if locate:
        result["verifier_exit"] = None
    return result


def passed(result: dict) -> bool:
    return (result["tests"] == result["passed"] == 4
            and result["pytest_exit"] == result["verifier_exit"] == 0)


def check_faulty(result: dict, *, locate: bool = False) -> None:
    if (result["tests"], result["failures"], result["passed"], result["pytest_exit"]) != (4, 2, 2, 1):
        raise RuntimeError(f"Signature du banc fautif inattendue : {result}")
    if not locate and result["verifier_exit"] != 1:
        raise RuntimeError(f"Refus du témoin fautif non démontré : {result}")


def run_baseline(stage: Path, sandbox_id: str, tag: str) -> dict:
    start = time.perf_counter()
    localization = guest_validate(sandbox_id, tag, "control", locate=True)
    check_faulty(localization, locate=True)
    sealed = stage / "baseline" / "notes_store.py"
    sealed.parent.mkdir()
    try:
        shutil.copyfile(BENCH / "reference" / "notes_reference_store.py", sealed)
        checked = guest_validate(sandbox_id, tag, "baseline")
    finally:
        sealed.unlink(missing_ok=True)
        sealed.parent.rmdir()
    return {"localization": localization, "validation": checked,
            "wall_s": time.perf_counter() - start, "functional_pass": passed(checked)}


def method_of(source: str) -> ast.FunctionDef:
    return next(method for node in ast.parse(source).body
                if isinstance(node, ast.ClassDef) and node.name == "NoteStore"
                for method in node.body if isinstance(method, ast.FunctionDef) and method.name == "save_note")


def method_text(source: str) -> str:
    method = method_of(source)
    return "\n".join(source.splitlines()[method.lineno - 1:method.end_lineno]) + "\n"


def first_code_block(response: str) -> str:
    if "</think>" in response:
        response = response.split("</think>", 1)[1]
    fence = chr(96) * 3
    block = re.search(rf"(?ms)^{fence}(?:python|py)?[ \t]*\n(.*?)^{fence}", response)
    return textwrap.dedent(block.group(1) if block else response).strip("\r\n")


def propose_change(source: str, output: str) -> tuple[str, str]:
    proposed = first_code_block(output)
    body = ast.parse(proposed).body
    method = method_of(source)
    if (len(body) != 1 or not isinstance(body[0], ast.FunctionDef)
            or body[0].name != "save_note" or body[0].decorator_list
            or ast.dump(body[0].args) != ast.dump(method.args)
            or ast.dump(body[0].returns) != ast.dump(method.returns)):
        raise ValueError("Fournir uniquement save_note avec sa signature d'origine.")
    lines = source.splitlines(keepends=True)
    replacement = (textwrap.indent(proposed, "    ") + "\n").splitlines(keepends=True)
    updated = lines[:method.lineno - 1] + replacement + lines[method.end_lineno:]
    diff = "".join(difflib.unified_diff(lines, updated, fromfile="a/notes_store.py", tofile="b/notes_store.py"))
    return diff, "".join(updated)


def build_diff(source: str, output: str) -> str:
    return propose_change(source, output)[0]


def apply_diff(work: Path, diff: str) -> None:
    if not diff:
        raise ValueError("Diff vide.")
    patch = work / "proposal.diff"
    patch.write_bytes(diff.encode("utf-8"))
    for options in (("--check",), ()):
        result = subprocess.run(["git", "apply", *options, str(patch)], cwd=work,
                                capture_output=True, timeout=12)
        if result.returncode:
            raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())


def infer(args, work: Path, prompt: str, seed: int, *, max_tokens: int = MAX_TOKENS,
          http_timeout_s: int = HTTP_TIMEOUT_S) -> tuple[dict, float, float]:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    http = request.build_opener(request.ProxyHandler({}))

    def call(route: str, data=None, timeout=2):
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        req = request.Request(f"http://127.0.0.1:{port}{route}", data=payload,
                              headers={"Content-Type": "application/json"})
        with http.open(req, timeout=bounded_timeout(timeout)) as response:
            return response.read().decode("utf-8")

    config = work / "rbitnet.toml"
    config.write_bytes(b"")
    env = {name: value for name, value in os.environ.items() if not name.upper().startswith("RBITNET_")}
    env.update(RBITNET_BIND=f"127.0.0.1:{port}", RBITNET_BACKEND="cpu",
               RBITNET_MODEL=str(args.model), RBITNET_TOKENIZER=str(args.tokenizer),
               RBITNET_CONFIG=str(config), RBITNET_CHAT_FORMAT="chatml",
               RBITNET_REQUIRE_MODEL_MATCH="1", HF_HUB_OFFLINE="1", RUST_LOG="info")
    cuda_library = getattr(args, "cuda_library", None)
    if cuda_library is not None:
        env.update(RBITNET_BACKEND="cuda", RBITNET_CUDA_QUANT_LIB=str(cuda_library),
                   RBITNET_MAX_VRAM_MB=str(args.vram_mib), CUDA_VISIBLE_DEVICES="0")
    limits = _model_limits.get()
    if limits is None and (memory := model_ram_limit(args)) is not None:
        limits = (8, memory)
    if limits:
        threads, memory = limits
        env.update(RAYON_NUM_THREADS=str(threads), RBITNET_I2S_THREADS=str(threads),
                   RBITNET_I2S_BATCH_THREADS=str(threads), RBITNET_MAX_LOAD_BYTES=str(memory * 1024 * 1024))
    bounded_timeout(20)
    with (work / "rbitnet.log").open("wb") as log:
        if limits:
            settings = ("RAYON_NUM_THREADS", "RBITNET_I2S_THREADS", "RBITNET_I2S_BATCH_THREADS", "RBITNET_MAX_LOAD_BYTES")
            line = " ".join(f"{key}={env[key]}" for key in settings) + "\n"
            log.write(line.encode("ascii"))
            log.flush()
        startup = time.perf_counter()
        process = subprocess.Popen([str(args.engine)], cwd=work, env=env, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while process.poll() is None and time.perf_counter() - startup < 20:
                bounded_timeout(2)
                try:
                    call("/ready")
                    break
                except (OSError, error.URLError):
                    time.sleep(0.2)
            else:
                log_text = (work / "rbitnet.log").read_text(encoding="utf-8", errors="replace")
                if any(f"exceeds {key}" in log_text for key in ("RBITNET_MAX_LOAD_BYTES", "RBITNET_MAX_VRAM_MB")):
                    raise ModelAdmissionBudgetExceeded("Le chargement Rbitnet dépasse le budget de mémoire.")
                raise RuntimeError("Rbitnet indisponible. Voir rbitnet.log.")
            startup_s = time.perf_counter() - startup
            model_id = json.loads(call("/v1/models"))["data"][0]["id"]
            begin = time.perf_counter()
            result = json.loads(call("/v1/chat/completions", {
                "model": model_id, "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens, "temperature": TEMPERATURE, "seed": seed,
                "stop": ["<|im_end|>"], "stream": False,
            }, timeout=http_timeout_s))
            return result, startup_s, time.perf_counter() - begin
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def feedback_prompt(result: dict, work: Path, source: str) -> str:
    if not result["diff_applied"]:
        return FIRST_PROMPT + method_text(source) + "\nPrevious output was rejected: " + result["diff_detail"][:240]
    candidate = (work / "notes_store.py").read_text(encoding="utf-8")
    checks = result["validation"]
    if checks["diagnosis"] == 1 and checks["verifier_exit"] == 0:
        return CLOSED_CONNECTION_PROMPT + method_text(candidate)
    return (
        FIRST_PROMPT + method_text(candidate)
        + f"\nPrevious validation: {checks['passed']}/{checks['tests']} tests passed, "
          f"{checks['failures']} assertions failed, {checks['errors']} errors, "
          f"verifier exit code {checks['verifier_exit']}. Repair the method and return the same format."
    )


def attempt(args, stage: Path, tag: str, work: Path, source: str, prompt: str, seed: int) -> dict:
    begin = time.perf_counter()
    work.mkdir()
    target = work / "notes_store.py"
    target.write_bytes(source.encode("utf-8"))
    (work / "prompt.txt").write_text(prompt, encoding="utf-8")
    row = {"seed": seed, "diff_applied": False}
    try:
        response, startup_s, generation_s = infer(args, work, prompt, seed)
        (work / "model-response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2),
                                                 encoding="utf-8")
        choice = response["choices"][0]
        row.update(startup_s=startup_s, generation_s=generation_s, usage=response.get("usage"),
                   finish_reason=choice.get("finish_reason"))
        diff = build_diff(source, choice["message"].get("content") or "")
        apply_diff(work, diff)
        row.update(diff_applied=True, diff_detail="git apply --check et git apply réussis.")
    except (SyntaxError, ValueError) as exc:
        row["diff_detail"] = str(exc)
    except (OSError, RuntimeError, KeyError, subprocess.SubprocessError) as exc:
        row["diff_detail"] = f"Échec d'exécution : {exc}"
    if row["diff_applied"]:
        staged = stage / work.name
        staged.mkdir()
        shutil.copy2(target, staged)
        name = work.name
    else:
        name = "control"
    row["tested"] = name
    row["validation"] = guest_validate(args.sandbox_id, tag, name)
    row["wall_s"] = time.perf_counter() - begin
    row["functional_pass"] = row["diff_applied"] and passed(row["validation"])
    return row


def write_report(output: Path, report: dict) -> None:
    draft = output / "report.tmp"
    draft.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    draft.replace(output / "report.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("engine", "model", "tokenizer", "python-runtime", "output"):
        parser.add_argument(f"--{option}", required=True, type=lambda path: Path(path).resolve())
    parser.add_argument("--sandbox-id", required=True)
    args = parser.parse_args()

    hashes = {name: file_hash(getattr(args, name)) for name in CHECKPOINTS}
    if hashes != CHECKPOINTS:
        raise RuntimeError(f"Binaire, modèle ou tokenizer différent du protocole gelé : {hashes}")
    active = [session["Id"] for session in wsb("list").get("WindowsSandboxEnvironments", ())]
    if active != [args.sandbox_id]:
        raise RuntimeError("Le bac désigné doit être l'unique session active.")
    source_file = BENCH / "notes" / "notes_store.py"
    source = source_file.read_bytes().decode("utf-8").replace("\r\n", "\n")
    args.output.mkdir(parents=True)
    stage = args.output / "input"
    stage.mkdir()
    fixtures = prepare(stage, args.python_runtime)
    (stage / "control").mkdir()
    (stage / "control" / "notes_store.py").write_bytes(source.encode("utf-8"))
    tag = secrets.token_hex(4)
    wsb("share", "--id", args.sandbox_id, "--host-path", str(stage),
        "--sandbox-path", fr"C:\AkashaGuidedInput-{tag}")
    control = guest_validate(args.sandbox_id, tag, "control")
    check_faulty(control)
    print(f"Témoin fautif dans le bac : {control}", flush=True)
    baseline = run_baseline(stage, args.sandbox_id, tag)
    report = {
        "protocol": "notes-cpu-guided-v1", "run": tag, "sandbox_id": args.sandbox_id,
        "model": args.model.name, "backend": "cpu", "hashes": hashes,
        "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(), "fixtures_sha256": fixtures,
        "runner_sha256": file_hash(Path(__file__)),
        "guest_runner_sha256": file_hash(stage / "validate_guided_notes.ps1"),
        "settings": {"max_tokens": MAX_TOKENS, "temperature": TEMPERATURE, "seeds": SEEDS,
                     "attempt_budget_s": ATTEMPT_BUDGET, "cycle_budget_s": CYCLE_BUDGET},
        "faulty_control": control, "sandbox_baseline": baseline, "cycles": [],
    }
    write_report(args.output, report)
    print(f"Baseline fixe dans le bac : {json.dumps(baseline, ensure_ascii=False)}", flush=True)
    if not baseline["functional_pass"]:
        raise RuntimeError("Contrôle positif de la baseline fixe en échec.")
    for index, seeds in enumerate(SEEDS, 1):
        start = time.perf_counter()
        prompt = FIRST_PROMPT + method_text(source)
        attempts = []
        for number, seed in enumerate(seeds, 1):
            work = args.output / f"cycle-{index}-attempt-{number}"
            print(f"Cycle {index}/3, tentative {number}/2, graine {seed}.", flush=True)
            result = attempt(args, stage, tag, work, source, prompt, seed)
            attempts.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            if result["functional_pass"]:
                break
            prompt = feedback_prompt(result, work, source)
        elapsed = time.perf_counter() - start
        within_budget = (elapsed <= CYCLE_BUDGET
                         and all(result["wall_s"] <= ATTEMPT_BUDGET for result in attempts))
        cycle = {"cycle": index, "attempts": attempts, "wall_s": elapsed,
                 "functional_pass": attempts[-1]["functional_pass"], "within_budget": within_budget,
                 "accepted": attempts[-1]["functional_pass"] and within_budget}
        report["cycles"].append(cycle)
        write_report(args.output, report)
        print(f"Cycle {index} : {elapsed:.1f} s, accepté={cycle['accepted']}.", flush=True)
    if source_file.read_text(encoding="utf-8") != source:
        raise RuntimeError("Le fichier fautif du dépôt a changé pendant la campagne.")
    return 0 if all(cycle["accepted"] for cycle in report["cycles"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
