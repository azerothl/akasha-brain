"""Vérifie la couverture des exigences structurées avant de produire une clause SQLite."""

import json
import re

from .tasks_sql_specialist import COMPARISONS, MAX_RESPONSE, compile_plan, exact_object

VERSION = "2.0.0"
INSTRUCTIONS = """Translate the requirements to one compact JSON line with keys "where" and "order".
Predicate syntax: [operator,column,literal] for = != < <= > >=,
["isnull",column] or ["notnull",column], ["and",predicate,predicate,...],
["or",predicate,predicate,...] or ["not",predicate]. Keep the parentheses as nested arrays.
Use null for "where" when all rows stay. Use [column,"asc"] or [column,"desc"]
for order keys. Append "first" or "last" as the third field for explicit NULL placement.
For ordered groups, use [["case",predicate,predicate,...],"asc"] as the first order key.
The predicates are tested in order, and nonmatching rows form the implicit last group.
Include every required condition, group and sort key. Use exactly the specified NULL placement.
Return only JSON, without SQL or explanation."""


class CoverageError(ValueError):
    def __init__(self, issues: list[str]):
        super().__init__(" ".join(issues))
        self.issues = issues


def parse_plan(answer: str) -> dict:
    if len(answer) > MAX_RESPONSE:
        raise ValueError("La réponse structurée dépasse la taille admise.")
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", answer.strip(), flags=re.IGNORECASE | re.DOTALL)
    try:
        plan = json.loads(fenced[1] if fenced else answer, object_pairs_hook=exact_object)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Return one complete JSON object.") from error
    if not isinstance(plan, dict) or set(plan) != {"where", "order"}:
        raise ValueError('The plan must have exactly "where" and "order".')
    return plan


def predicate_key(node: object, depth: int = 0) -> tuple:
    """Préserve les branches logiques et normalise l'ordre de leurs termes."""
    if depth >= 8 or not isinstance(node, list) or not 2 <= len(node) <= 9 or not isinstance(node[0], str):
        raise ValueError("A required predicate is malformed.")
    op, *args = node
    if op in ("and", "or") and len(args) >= 2:
        children = {child for arg in args for child in flattened(predicate_key(arg, depth + 1), op)}
        return (op, *sorted(children))
    if op == "not" and len(args) == 1:
        return (op, predicate_key(args[0], depth + 1))
    if op in ("isnull", "notnull") and len(args) == 1 and isinstance(args[0], str):
        return op, args[0]
    if op in COMPARISONS and len(args) == 2 and isinstance(args[0], str) and type(args[1]) in (int, str):
        return op, args[0], json.dumps(args[1], ensure_ascii=False)
    raise ValueError("A predicate has an unsupported operator or arguments.")


def flattened(key: tuple, op: str) -> tuple:
    return key[1:] if key[0] == op else (key,)


def order_parts(order: object) -> tuple[list, list, list]:
    if not isinstance(order, list) or not 1 <= len(order) <= 8:
        raise ValueError("The plan must contain the required order keys.")
    groups, keys, nulls = [], [], []
    for index, key in enumerate(order):
        if not isinstance(key, list) or len(key) not in (2, 3) or key[1] not in ("asc", "desc"):
            raise ValueError("An order key is malformed.")
        value, direction = key[:2]
        if isinstance(value, list) and 2 <= len(value) <= 9 and value[0] == "case":
            groups.append((index, tuple(predicate_key(predicate) for predicate in value[1:]), direction))
        elif isinstance(value, str):
            keys.append((value, direction))
        else:
            raise ValueError("An order key must use a column or ordered case groups.")
        if len(key) == 3:
            if key[2] not in ("first", "last"):
                raise ValueError("NULL placement must be first or last.")
            nulls.append((index, key[2]))
    return groups, keys, nulls


def predicate_text(node: list) -> str:
    op, *args = node
    if op in ("and", "or"):
        return "(" + f" {op.upper()} ".join(predicate_text(child) for child in args) + ")"
    if op == "not":
        return f"NOT {predicate_text(args[0])}"
    if op in ("isnull", "notnull"):
        return f"{args[0]} IS {'NOT ' if op == 'notnull' else ''}NULL"
    return f"{args[0]} {op} {json.dumps(args[1], ensure_ascii=False)}"


def order_text(order: list) -> str:
    items = []
    for value, direction, *nulls in order:
        if isinstance(value, list):
            rules = "; ".join(predicate_text(condition) for condition in value[1:])
            value = f"CASE groups ({rules}; implicit remainder)"
        suffix = f" NULLS {nulls[0].upper()}" if nulls else ""
        items.append(f"{value} {direction.upper()}{suffix}")
    return ", then ".join(items)


def verify_coverage(plan: dict, required: dict) -> None:
    expected_where = required["where"]
    required_selection = predicate_key(expected_where) if expected_where is not None else None
    expected_groups, expected_keys, expected_nulls = order_parts(required["order"])
    issues = []
    try:
        selection = predicate_key(plan["where"]) if plan["where"] is not None else None
        if selection != required_selection:
            if expected_where is None:
                issues.append('Selection: use "where":null to keep every row.')
            else:
                issues.append(f"Selection must cover exactly {predicate_text(expected_where)}.")
    except ValueError as error:
        issues.append(str(error))
    try:
        groups, keys, nulls = order_parts(plan["order"])
        if groups != expected_groups:
            issues.append(f"Group coverage or priority is incorrect. Required order: {order_text(required['order'])}.")
        if keys != expected_keys:
            issues.append(f"Sort keys or directions are incorrect. Required order: {order_text(required['order'])}.")
        if nulls != expected_nulls:
            issues.append(f"Explicit NULL placement is incorrect. Required order: {order_text(required['order'])}.")
    except ValueError as error:
        issues.append(str(error))
    if issues:
        raise CoverageError(issues)


def compile_checked(plan: dict, required: dict, columns: frozenset[str]) -> str:
    verify_coverage(plan, required)
    return compile_plan(plan, columns)


def specialist_prompt(intent: str, schema: str, target: str, current: str,
                      required: dict, feedback: str | None) -> str:
    where = required["where"]
    selection = predicate_text(where) if where is not None else "keep all rows"
    correction = f"\nPrevious attempt: {feedback}" if feedback else ""
    return (f"{INSTRUCTIONS}\n\nTask: {intent}\nTarget filter: {target}\nCurrent clause: {current}\n"
            f"SQLite schema:\n{schema}\nRequired selection: {selection}\n"
            f"Required order: {order_text(required['order'])}{correction}\n\nJSON:")
