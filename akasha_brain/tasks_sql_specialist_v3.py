"""Format plat du spécialiste Tâches, converti en plan soumis à la garde v2."""

import ast
import json
import re
from string import ascii_uppercase

from .tasks_sql_specialist import MAX_RESPONSE, exact_object
from .tasks_sql_specialist_v2 import predicate_text

VERSION = "3.0.0"
FIELDS = {"where", "groups", "order"}
INSTRUCTIONS = """Return one compact JSON object with three string fields: "where", "groups", "order".
Use the named conditions below. In expressions use & for AND, | for OR, ~ for NOT, and parentheses.
Use an empty "where" string to keep every row. In "groups" separate the ordered expressions
with semicolons, or use an empty string. All remaining rows form the implicit last group.
In "order" use semicolon-separated keys in the form column asc or column desc.
Append first or last to a key only for explicit NULL placement.
Return only JSON, with no nested arrays, SQL or explanation."""


def named_requirements(required: dict) -> tuple[dict, str, list[str], list]:
    """Nomme les prédicats atomiques du contrat dans un ordre déterministe."""
    atoms = {}
    labels = {}

    def express(node: list) -> str:
        op, *args = node
        if op in ("and", "or"):
            return "(" + f" {op.upper()} ".join(express(child) for child in args) + ")"
        if op == "not":
            return f"NOT {express(args[0])}"
        key = tuple(node)
        if key not in labels:
            if len(labels) == len(ascii_uppercase):
                raise ValueError("Trop de prédicats pour le format v3.")
            label = ascii_uppercase[len(labels)]
            labels[key] = label
            atoms[label] = node
        return labels[key]

    where = express(required["where"]) if required["where"] is not None else ""
    order = required["order"]
    rank = order[0]
    groups = []
    if isinstance(rank[0], list):
        groups = [express(node) for node in rank[0][1:]]
        order = order[1:]
    return atoms, where, groups, order


def specialist_prompt(intent: str, target: str, required: dict, feedback: str | None) -> str:
    atoms, where, groups, order = named_requirements(required)
    definitions = "\n".join(f"{label}: {predicate_text(node)}" for label, node in atoms.items())
    correction = f"\nPrevious attempt: {feedback}" if feedback else ""
    return (f"{INSTRUCTIONS}\n\nTask: {intent}\nTarget filter: {target}\n"
            f"Named conditions:\n{definitions}\n"
            f"Selection to express: {where or 'keep every row'}\n"
            f"Groups to express: {'; '.join(groups) or 'none'}\n"
            f"Sort to express: {'; '.join(' '.join(key) for key in order)}{correction}\n\nJSON:")


def parse_response(answer: str) -> tuple[dict, bool]:
    if len(answer) > MAX_RESPONSE:
        raise ValueError("La réponse structurée dépasse la taille admise.")
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", answer.strip(), flags=re.IGNORECASE | re.DOTALL)
    content = fenced[1] if fenced else answer.strip()
    try:
        plan, end = json.JSONDecoder(object_pairs_hook=exact_object).raw_decode(content)
    except (json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Return one complete JSON object.") from error
    tail = content[end:].strip()
    if tail not in ("", "}"):
        raise ValueError("Return one JSON object without trailing content.")
    if not isinstance(plan, dict) or set(plan) != FIELDS or any(not isinstance(value, str) for value in plan.values()):
        raise ValueError('The plan must contain only the strings "where", "groups" and "order".')
    return plan, tail == "}"


def expression(text: str, atoms: dict) -> list:
    text = re.sub(r"\b(?:AND|OR|NOT)\b", lambda word: {"AND": "&", "OR": "|", "NOT": "~"}[word[0].upper()],
                  text.strip(), flags=re.IGNORECASE)
    if len(text) > 256 or not re.fullmatch(r"[A-Z&|~() \t]+", text):
        raise ValueError("Use named conditions and & | ~ with parentheses.")
    try:
        parsed = ast.parse(text, mode="eval")
    except (SyntaxError, RecursionError) as error:
        raise ValueError("The condition expression is malformed.") from error

    def predicate(node: ast.AST) -> list:
        if isinstance(node, ast.Name) and node.id in atoms:
            return atoms[node.id]
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Invert):
            return ["not", predicate(node.operand)]
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitAnd, ast.BitOr)):
            op = "and" if isinstance(node.op, ast.BitAnd) else "or"
            children = [predicate(node.left), predicate(node.right)]
            return [op, *(term for child in children for term in (child[1:] if child[0] == op else [child]))]
        raise ValueError("A condition is unknown or uses an unsupported operator.")

    return predicate(parsed.body)


def expand_plan(plan: dict, required: dict) -> dict:
    atoms, _, _, _ = named_requirements(required)
    where = expression(plan["where"], atoms) if plan["where"].strip() else None
    order = [key.strip().split() for key in plan["order"].split(";")]
    if plan["groups"].strip():
        predicates = [expression(group, atoms) for group in plan["groups"].split(";")]
        order.insert(0, [["case", *predicates], "asc"])
    return {"where": where, "order": order}
