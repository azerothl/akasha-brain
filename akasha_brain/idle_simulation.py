"""Évalue des sélections Notes sur des cas synthétiques pendant l’inactivité."""

import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from itertools import product
import os
from pathlib import Path
from random import Random
from time import monotonic, thread_time
from uuid import uuid4

from bench.run_guided_repair import write_report
from .desktop_state import decode_notes_observation
from .model_resources import available_ram
from .notes_link_promotion import digest
from .planning import PlanningError


PLANS = {"observe": [], "save": ["save"], "restart": ["restart"], "save_restart": ["save", "restart"]}


@dataclass(frozen=True)
class SimulationBudget:
    cases: int = 16
    wall_s: float = 2
    cpu_s: float = 0.5
    minimum_free_ram_mib: int = 512
    maximum_host_cpu: float = 0.35
    interval_s: int = 900

    def __post_init__(self):
        if (not 1 <= self.cases <= 64 or self.wall_s <= 0 or self.cpu_s <= 0
                or self.minimum_free_ram_mib <= 0 or not 0 < self.maximum_host_cpu <= 1 or self.interval_s <= 0):
            raise ValueError("Budget de simulation invalide.")


class WindowsLoad:
    def __init__(self):
        self.previous = None

    def __call__(self) -> float | None:
        if os.name != "nt":
            return None
        idle, kernel, user = (wintypes.FILETIME() for _ in range(3))
        get_times = ctypes.windll.kernel32.GetSystemTimes
        get_times.argtypes = (ctypes.POINTER(wintypes.FILETIME),) * 3
        get_times.restype = wintypes.BOOL
        if not get_times(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        idle_ticks, kernel_ticks, user_ticks = (
            value.dwHighDateTime << 32 | value.dwLowDateTime for value in (idle, kernel, user)
        )
        current = (idle_ticks, kernel_ticks + user_ticks)
        previous, self.previous = self.previous, current
        if previous is None or current[1] <= previous[1]:
            return None
        return max(0.0, min(1.0, 1 - (current[0] - previous[0]) / (current[1] - previous[1])))


def synthetic_cases(seed: int, count: int):
    random = Random(seed)
    combinations = [(saved, restart, faulty) for saved, restart, faulty in product((False, True), repeat=3)]
    for index in range(count):
        saved, restart, faulty = combinations[index % len(combinations)]
        yield {"id": f"sim-notes-{index:02}", "saved": saved, "restart": restart,
               "faulty": faulty, "pid": random.randrange(1, 0xFFFFF)}


def replay_case(case: dict) -> dict:
    from bench.run_phase5_notes_action_selection import select_plan, verify_final

    before = snapshot(case["pid"], case["saved"])
    goal = {"exact_fixture_present": True, "pid_relation": "different" if case["restart"] else "any"}
    trials = {}
    for variant, predictor in (("reference", False), ("candidate", True)):
        selection = select_plan(PLANS, goal, before, use_predictor=predictor)
        saved = case["saved"] or ("save" in selection["steps"] and not case["faulty"])
        pid = case["pid"] + int("restart" in selection["steps"])
        checks = verify_final(goal, before, snapshot(pid, saved))
        trials[variant] = {"chosen": selection["chosen"], "passed": all(checks.values())}
    return {"case": case["id"], "input_sha256": digest(case), "trials": trials}


def snapshot(pid: int, saved: bool) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    packet = 0x6000001F | (pid << 8) | (0x20 if saved else 0)
    state = decode_notes_observation(packet, started_at=now, finished_at=now)
    state["provenance"] = {"scope": "synthetic_notes_simulation"}
    return state


class IdleSimulations:
    def __init__(self, directory: Path, scheduler, *, budget=None, load=None):
        self.directory = directory / "idle-simulations"
        self.scheduler = scheduler
        self.budget = budget or SimulationBudget()
        self.load = load if load is not None else WindowsLoad()
        self.next_trial = 0.0

    def tick(self):
        cpu = self.load()
        if cpu is None or cpu > self.budget.maximum_host_cpu or monotonic() < self.next_trial:
            return None
        try:
            ram_mib = available_ram()
        except PlanningError:
            return None
        if ram_mib < self.budget.minimum_free_ram_mib:
            return None
        job = self.scheduler.submit_if_idle(lambda: self.run(cpu, ram_mib))
        if job is not None:
            self.next_trial = monotonic() + self.budget.interval_s
        return job

    def run(self, cpu, ram_mib):
        started, cpu_start = monotonic(), thread_time()
        run_id = uuid4()
        seed = run_id.int & 0xFFFFFFFF
        trials = []
        status = "evaluated"
        for case in synthetic_cases(seed, self.budget.cases):
            if self.scheduler.interactive_pending():
                status = "preempted"
                break
            if monotonic() - started >= self.budget.wall_s or thread_time() - cpu_start >= self.budget.cpu_s:
                status = "budget_exhausted"
                break
            trials.append(replay_case(case))
        if self.scheduler.interactive_pending():
            status = "preempted"
        if status == "evaluated" and (monotonic() - started > self.budget.wall_s
                                      or thread_time() - cpu_start > self.budget.cpu_s):
            status = "budget_exhausted"
        result = {"status": status, "scope": "synthetic_notes_simulation", "seed": seed,
                  "budget": asdict(self.budget), "host_cpu": round(cpu, 4), "host_free_ram_mib": ram_mib,
                  "candidate": {"parent": "notes-selection-reference", "policy": "notes-selection-predictor"},
                  "trials": trials, "wall_s": round(monotonic() - started, 6),
                  "cpu_s": round(thread_time() - cpu_start, 6)}
        folder = self.directory / str(run_id)
        folder.mkdir(parents=True)
        write_report(folder, result)
        return result
