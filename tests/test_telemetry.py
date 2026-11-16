import json

from akasha_brain.telemetry import SCHEMA_URL, export_trace


def test_maps_each_invocation_and_dependency_without_exporting_content():
    moment = "2026-11-16T00:00:00+00:00"
    plan = {"graph_id": "notes-rbitnet", "graph_version": "1.0.0",
            "goal_id": "123e4567-e89b-12d3-a456-426614174001", "user_intent": "private-objective",
            "steps": [
                {"id": "generate_diff", "capability_id": "notes.generate", "version": "1.0.0", "depends_on": []},
                {"id": "verify", "capability_id": "notes.verify", "version": "1.0.0", "depends_on": ["generate_diff"]},
            ]}
    report = {
        "graph": plan, "status": "passed", "started_at": moment, "wall_s": 5.0,
        "sandbox_id": "5dda6fc9-e214-45d4-b50a-26ea71514c18", "repair": {"model": "model.gguf"},
        "trace": [
            {"id": "generate_diff", "started_at": moment, "wall_s": 0.25, "status": "failed", "attempt": 1,
             "result": {"prompt": "private-prompt"}},
            {"id": "generate_diff", "started_at": moment, "wall_s": 1.25, "status": "passed", "attempt": 2,
             "result": {"seed": 742, "diff": "private-diff",
                        "residency": {"ram_reserved_mib": 8192, "device_vram_free_mib": None,
                                      "command": "private-command"}}},
            {"id": "verify", "started_at": moment, "wall_s": 0.75, "status": "passed", "attempt": 2},
        ],
    }
    projection = export_trace(report)
    scope = projection["resourceSpans"][0]["scopeSpans"][0]
    assert scope["schemaUrl"] == SCHEMA_URL
    root, first, second, verify = scope["spans"]
    assert all(span["traceId"] == root["traceId"] and len(span["spanId"]) == 16 for span in scope["spans"])
    assert all(span["parentSpanId"] == root["spanId"] for span in (first, second, verify))
    assert int(root["endTimeUnixNano"]) - int(root["startTimeUnixNano"]) == 5_000_000_000
    assert verify["links"] == [{"traceId": root["traceId"], "spanId": second["spanId"]}]
    assert first["status"]["code"] == 2 and second["status"]["code"] == 0
    assert second["kind"] == 3 and second["name"] == "chat model.gguf"
    assert {"key": "gen_ai.request.seed", "value": {"intValue": "742"}} in second["attributes"]
    assert {"key": "akasha.resource.ram_reserved_mib", "value": {"intValue": "8192"}} in second["attributes"]
    assert not any(item["key"] == "akasha.resource.device_vram_free_mib" for item in second["attributes"])
    assert "private-" not in json.dumps(projection)
