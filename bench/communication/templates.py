"""Rendu local des fiches structurées de clarification et d'étapes."""

import re


def render_template(fiche: str) -> str | None:
    """Rend les deux états pris en charge. Les autres passent au modèle."""
    state, _, remainder = fiche.partition(";")
    if state not in {"État=info manquante", "État=à venir"}:
        return None

    fields = {}
    for field in remainder.split(";"):
        key, separator, value = field.strip().partition("=")
        if separator:
            if key in fields:
                raise ValueError(f"Champ dupliqué dans la fiche ({key})")
            fields[key] = value.strip()

    if state == "État=info manquante":
        subject = fields.get("objet", "").rstrip(".")
        if not subject:
            raise ValueError("La clarification requiert un objet")
        return f"Pouvez-vous préciser {subject} ?"

    steps = {}
    for key, value in fields.items():
        if key.startswith("étape "):
            number = re.fullmatch(r"étape ([1-9][0-9]*)", key)
            clause = value.rstrip(".")
            if number is None or not clause:
                raise ValueError(f"Étape invalide dans la fiche ({key})")
            steps[int(number[1])] = clause
    if not steps:
        raise ValueError("La fiche d'ordre requiert des étapes numérotées")

    return "\n".join(
        f"{number}. {clause[0].upper()}{clause[1:]}."
        for number, clause in sorted(steps.items())
    )
