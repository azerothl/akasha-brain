"""Projection locale et minimisée d'une trace vers OTLP JSON."""

import argparse
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

from contracts.akasha_contracts.errors import ErrorCode

SEMANTIC_CONVENTIONS = "1.37.0"
SCHEMA_URL = f"https://opentelemetry.io/schemas/{SEMANTIC_CONVENTIONS}"
SCOPE_VERSION = "1.0.0"
NANOSECONDS = 1_000_000_000
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")


def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError("Identifiant technique de trace invalide.")
    return value


def unix_nanos(value: str) -> int:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        raise ValueError("L’heure du span doit inclure un fuseau.")
    return int(moment.timestamp()) * NANOSECONDS + moment.microsecond * 1000


def duration_nanos(seconds) -> int:
    value = Decimal(str(seconds))
    if not value.is_finite() or value < 0:
        raise ValueError("Durée de trace invalide.")
    return int(value * NANOSECONDS)


def attribute(key, value):
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    return {"key": key, "value": {"stringValue": value}}


def status(value: str) -> dict:
    if value not in ("passed", "failed"):
        raise ValueError("La trace doit être terminée avant l’export.")
    return {"code": 2 if value == "failed" else 0}


def export_trace(report: dict) -> dict:
    graph = report["graph"]
    graph_id, graph_version = identifier(graph["graph_id"]), identifier(graph["graph_version"])
    execution = UUID(report["sandbox_id"]) if report.get("sandbox_id") else uuid4()
    trace_id = execution.hex
    if not execution.int:
        raise ValueError("Identifiant de bac invalide.")
    steps = {item["id"]: item for item in graph["steps"]}

    def span(number, name, kind, start, end, result, attrs):
        span_id = sha256(f"{trace_id}:{number}".encode("ascii")).hexdigest()[:16]
        return {"traceId": trace_id, "spanId": span_id, "name": name, "kind": kind,
                "startTimeUnixNano": str(start), "endTimeUnixNano": str(end),
                "status": status(result), "attributes": [attribute(key, value) for key, value in attrs.items()]}

    core = {
        "akasha.goal.id": str(UUID(graph["goal_id"])), "akasha.graph.id": graph_id, "akasha.graph.version": graph_version,
    }
    nodes = []
    preceding = {}
    model = report.get("repair", {}).get("model")
    for number, row in enumerate(report["trace"], start=1):
        node_id = identifier(row["id"])
        planned = steps[node_id]
        start = unix_nanos(row["started_at"])
        end = start + duration_nanos(row["wall_s"])
        attrs = {"akasha.node.id": node_id, "akasha.capability.id": identifier(planned["capability_id"]),
                 "akasha.capability.version": identifier(planned["version"])}
        attempt = row.get("attempt")
        if type(attempt) is int and attempt > 0:
            attrs["akasha.attempt"] = attempt
        residency = row.get("result", {}).get("residency", {})
        for key in ("ram_reserved_mib", "vram_reserved_mib", "host_ram_free_mib", "device_vram_free_mib"):
            if type(residency.get(key)) is int:
                attrs[f"akasha.resource.{key}"] = residency[key]
        name, kind = node_id, 1
        if node_id == "generate_diff" and model is not None:
            model_name = identifier(model)
            attrs.update({"gen_ai.operation.name": "chat", "gen_ai.provider.name": "rbitnet",
                          "gen_ai.request.model": model_name})
            if type(row.get("result", {}).get("seed")) is int:
                attrs["gen_ai.request.seed"] = row["result"]["seed"]
            name, kind = "chat " + model_name, 3
        if row["status"] == "failed":
            attrs["error.type"] = "node_failed"
        entry = span(number, name, kind, start, end, row["status"], attrs)
        entry["links"] = [{"traceId": trace_id, "spanId": preceding[dependency]}
                          for dependency in planned["depends_on"] if dependency in preceding]
        preceding[node_id] = entry["spanId"]
        nodes.append(entry)

    starts = [int(node["startTimeUnixNano"]) for node in nodes]
    ends = [int(node["endTimeUnixNano"]) for node in nodes]
    if "started_at" in report:
        starts.append(unix_nanos(report["started_at"]))
        ends.append(starts[-1] + duration_nanos(report["wall_s"]))
    if not starts:
        raise ValueError("La trace ne contient aucun instant mesuré.")
    if report["status"] == "failed":
        error_code = report.get("error", {}).get("code")
        core["error.type"] = error_code if error_code in {code.value for code in ErrorCode} else "workflow_failed"
    root = span(0, graph_id, 1, min(starts), max(ends), report["status"], core)
    for node in nodes:
        node["parentSpanId"] = root["spanId"]
    return {"resourceSpans": [{
        "resource": {"attributes": [attribute("service.name", "akasha-brain")]},
        "scopeSpans": [{"schemaUrl": SCHEMA_URL, "scope": {"name": "akasha.trace", "version": SCOPE_VERSION},
                        "spans": [root, *nodes]}],
    }]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    projection = export_trace(json.loads(args.report.read_bytes()))
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(projection, output, ensure_ascii=False, indent=2)
        output.write("\n")


if __name__ == "__main__":
    main()
