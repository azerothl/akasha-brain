"""Contrat et compilateur du spécialiste de clauses SQLite Tâches."""

import json
import re

VERSION = "1.0.0"
COMPARISONS = {"=", "!=", "<", "<=", ">", ">="}
MAX_RESPONSE = 4096
INSTRUCTIONS = """Return one compact JSON object with exactly "where" and "order".
"where" contains the conditions for keeping rows, or null when all rows must stay.
Predicate arrays: ["=",column,value], ["!=",column,value], ["<",column,value],
["<=",column,value], [">",column,value], [">=",column,value], ["isnull",column],
["notnull",column], ["and",predicate,predicate,...], ["or",predicate,predicate,...],
or ["not",predicate]. A comparison value is a string or an integer.
"order" is an array of keys in priority order. Each key is [column,"asc"] or
[column,"desc"]. Append "first" or "last" as a third item for explicit NULL placement.
For ordered groups, use [["case",predicate,predicate,...],"asc"] as the first key.
Each predicate is a WHEN, in order. Rows matching none form the final group.
Then add the keys used to sort within groups. Grouping or ordering alone keeps all rows.
Check each requirement against the schema. Keep constraints that still apply to the
target filter. Use the exact column names. Return compact JSON only, without text or SQL."""


def specialist_prompt(intent: str, schema: str, source: str, target: str, current: str, feedback: str | None) -> str:
    evidence = f"\nIndependent feedback on the previous attempt:\n{feedback}" if feedback else ""
    return (
        f"{INSTRUCTIONS}\n\nTask: {intent}\nFilter to repair: {target}\n"
        f"Current clause: {current}\nSQLite schema:\n{schema}\nPython module:\n{source}{evidence}\n\nJSON:"
    )


def exact_object(items: list[tuple[str, object]]) -> dict:
    result = dict(items)
    if len(result) != len(items):
        raise ValueError("Le plan SQL contient une clé JSON répétée.")
    return result


def column_sql(value: object, columns: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in columns:
        raise ValueError("Le plan SQL doit utiliser une colonne du schéma.")
    return '"' + value.replace('"', '""') + '"'


def literal_sql(value: object) -> str:
    if type(value) is int and -(2 ** 63) <= value < 2 ** 63:
        return str(value)
    if isinstance(value, str) and len(value) <= 128 and value.isprintable():
        return "'" + value.replace("'", "''") + "'"
    if value == "":
        return "''"
    raise ValueError("Une comparaison attend un entier SQLite ou du texte imprimable.")


def predicate_sql(node: object, columns: frozenset[str], depth: int = 0) -> str:
    if depth >= 8 or not isinstance(node, list) or not 2 <= len(node) <= 9 or not isinstance(node[0], str):
        raise ValueError("Le plan SQL contient un prédicat invalide ou trop profond.")
    op, *args = node
    if op in ("and", "or") and len(args) >= 2:
        operands = [predicate_sql(child, columns, depth + 1) for child in args]
        return "(" + f" {op.upper()} ".join(operands) + ")"
    if op == "not" and len(args) == 1:
        return f"(NOT {predicate_sql(args[0], columns, depth + 1)})"
    if op in ("isnull", "notnull") and len(args) == 1:
        suffix = "IS NULL" if op == "isnull" else "IS NOT NULL"
        return f"({column_sql(args[0], columns)} {suffix})"
    if op in COMPARISONS and len(args) == 2:
        return f"({column_sql(args[0], columns)} {op} {literal_sql(args[1])})"
    raise ValueError("Opérateur ou nombre d'arguments non pris en charge dans la sélection.")


def sort_key_sql(key: object, columns: frozenset[str]) -> str:
    if not isinstance(key, list) or len(key) not in (2, 3):
        raise ValueError("Chaque clé de tri exige une expression, un sens et éventuellement une position NULL.")
    expression, direction = key[:2]
    if direction not in ("asc", "desc"):
        raise ValueError("Le sens du tri doit être asc ou desc.")
    if len(key) == 3 and key[2] not in ("first", "last"):
        raise ValueError("La position des NULL doit être first ou last.")
    if isinstance(expression, list):
        if not 2 <= len(expression) <= 9 or expression[0] != "case":
            raise ValueError("Un groupe de tri exige case suivi de prédicats ordonnés.")
        conditions = expression[1:]
        groups = " ".join(f"WHEN {predicate_sql(condition, columns)} THEN {index}"
                          for index, condition in enumerate(conditions))
        expression = f"CASE {groups} ELSE {len(conditions)} END"
    else:
        expression = column_sql(expression, columns)
    nulls = f" NULLS {key[2].upper()}" if len(key) == 3 else ""
    return f"{expression} {direction.upper()}{nulls}"


def compile_plan(plan: object, columns: frozenset[str]) -> str:
    if not isinstance(plan, dict) or set(plan) != {"where", "order"}:
        raise ValueError('Le plan SQL doit contenir exactement les clés "where" et "order".')
    order = plan["order"]
    if not isinstance(order, list) or not 1 <= len(order) <= 8:
        raise ValueError("Le plan SQL exige entre une et huit clés de tri.")
    selection = f"WHERE {predicate_sql(plan['where'], columns)} " if plan["where"] is not None else ""
    return selection + "ORDER BY " + ", ".join(sort_key_sql(key, columns) for key in order)


def decode_plan(answer: str, columns: frozenset[str]) -> tuple[dict, str]:
    if len(answer) > MAX_RESPONSE:
        raise ValueError("La réponse structurée dépasse la taille admise.")
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", answer.strip(), flags=re.IGNORECASE | re.DOTALL)
    try:
        plan = json.loads(fenced[1] if fenced else answer, object_pairs_hook=exact_object)
    except json.JSONDecodeError as error:
        raise ValueError("La réponse du spécialiste doit former un seul objet JSON complet.") from error
    return plan, compile_plan(plan, columns)
