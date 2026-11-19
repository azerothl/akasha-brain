"""Charge au démarrage les déclarations HTTPS choisies par l’opérateur."""

from dataclasses import dataclass
from hashlib import sha256
from ipaddress import ip_address
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from contracts.akasha_contracts.validate import validate
from .specialist_registry import load_specialists

ADAPTER = "service-https-json.v1"
DEFAULT_REGISTRY = Path(__file__).with_name("service_adapters.json")
MANIFEST_SCHEMA = Path(__file__).with_name("service_adapter.schema.json")
TIMEOUT_S = 5
MAX_BYTES = 8192


class ServiceError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Operation:
    id: str
    path: str
    method: str
    effect: str
    purpose: str
    inputs: dict
    outputs: dict

    @property
    def writes(self):
        return self.effect == "persistent"

    def manifest(self, service):
        destination = service.origin + self.path
        permissions = {"network": [destination], "reads": list(self.inputs["properties"]),
                       "writes": [destination] if self.writes else []}
        if service.authenticated:
            permissions["reads"].extend(["connection:identity", "vault:connection-api-key"])
        return {"capability_id": self.id, "kind": "adapter", "version": service.version,
                "description": self.purpose, "input_schema": self.inputs, "output_schema": self.outputs,
                "permissions": permissions, "side_effects": "persistent" if self.writes else "none",
                "risk_class": "R3", "sandbox": {"tier": "none", "network_egress": True, "time_s": TIMEOUT_S}}


@dataclass(frozen=True)
class Service:
    id: str
    version: str
    origin: str
    authenticated: bool
    operations: tuple[Operation, ...]
    fingerprint: str

    def operation(self, capability):
        for op in self.operations:
            if op.id == capability:
                return op
        raise ServiceError("operation_unavailable")

    def describe(self):
        return {"service": self.id, "origin": self.origin, "adapter": ADAPTER, "version": self.version,
                "authentication": "api_key" if self.authenticated else "none",
                "budget": {"seconds": TIMEOUT_S, "bytes_per_message": MAX_BYTES, "requests": 1},
                "operations": [op.manifest(self) for op in self.operations]}


def validate_origin(origin):
    if not re.fullmatch(r"https://(?:[a-z0-9.-]+|\[[0-9a-f:]+\])(?::[1-9][0-9]{0,4})?", origin):
        raise ValueError()
    url = urlsplit(origin)
    if url.port is not None and url.port > 65535:
        raise ValueError()
    host = url.hostname
    try:
        ip_address(host)
    except ValueError:
        labels = host.split(".")
        if (len(labels) < 2 or len(host) > 253 or labels[-1].isdigit()
                or not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
            raise ValueError()


def unique_keys(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError()
    return result


def load_registry(path=DEFAULT_REGISTRY):
    engines = load_specialists(Path(__file__).with_name("service_specialists.json"))
    if not any(item.contract == ADAPTER and item.engine == "https-json" and not item.fallback for item in engines):
        raise ServiceError("adapter_unavailable")
    validator = Draft202012Validator(json.loads(MANIFEST_SCHEMA.read_bytes()))
    services, capabilities = {}, set()
    try:
        with path.open("rb") as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError()
        entries = json.loads(raw, object_pairs_hook=unique_keys)
        if not validator.is_valid(entries):
            raise ValueError()
        for entry in entries:
            validate_origin(entry["origin"])
            if entry["id"] in services:
                raise ValueError()
            operations = []
            for spec in entry["operations"]:
                if spec["id"] in capabilities or (spec["method"] == "GET") != (spec["effect"] == "read"):
                    raise ValueError()
                capabilities.add(spec["id"])
                for schema in (spec["input_schema"], spec["output_schema"]):
                    if not set(schema["required"]) <= set(schema["properties"]):
                        raise ValueError()
                operations.append(Operation(spec["id"], spec["path"], spec["method"], spec["effect"],
                                            spec["purpose"], spec["input_schema"], spec["output_schema"]))
            fingerprint = sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest()
            service = Service(entry["id"], entry["version"], entry["origin"], entry["authentication"] == "api_key",
                              tuple(operations), fingerprint)
            if any(validate(op.manifest(service), "CapabilityManifest") for op in operations):
                raise ValueError()
            services[service.id] = service
    except (OSError, ValueError, RecursionError):
        raise ServiceError("registry_invalid") from None
    return services
