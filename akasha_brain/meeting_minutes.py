"""Compte rendu extractif de propos français. Les voix ne sont pas identifiées."""

import re

from .whisper_pilot import MANIFEST as ASR_MANIFEST

CAPABILITY = "audio.meeting_minutes"
MANIFEST = {**ASR_MANIFEST, "capability_id": CAPABILITY,
            "description": "Résumer une réunion française et citer les décisions et actions avec leurs horodatages."}

REQUEST = re.compile(r"(?:(?:peux-tu|pouvez-vous)\s+)?(?:analys(?:e|ez)|résum(?:e|ez)|"
                     r"(?:fais|donne)(?:-moi)?\s+(?:le|un)\s+(?:résumé|compte rendu)(?:\s+de)?)"
                     r"\s+(?:(?:la|cette)\s+réunion\s+)?@\s*[.!?]?", re.I)
DECISION = re.compile(r"^(?:(?:nous (?:avons décidé|décidons|retenons|validons|confirmons)|"
                      r"on (?:a décidé|décide|retient|valide|confirme))\b|"
                      r"(?:décision(?: prise| retenue)?|c['’]est décidé)\s*[:,])", re.I)
ACTION = re.compile(r"^(?:(?P<subject>[\wÀ-ÿ’'-]+(?:\s+(?:et|ou)\s+[\wÀ-ÿ’'-]+)?)\s+"
                    r"(?:(?:doit|doivent|vais|va|allons|vont|devons)(?=\s+(?:ne pas |se |le |la |les )?"
                    r"(?:[ls]['’])?[\w-]+(?:er|ir|re)\b)|se charge(?:nt)? de|"
                    r"s['’]engage(?:nt)? à|me charge de)\s+|(?:il faut|à faire\s*[:,]|action\s*[:,])\s*)", re.I)
TENTATIVE = re.compile(r"\b(?:peut-être|éventuellement|à confirmer|sous réserve|si jamais|"
                       r"reste une proposition|pas encore décidé|rien n['’]est décidé|reste à décider)\b", re.I)
ALTERNATIVE_OWNER = re.compile(r"\b(?:ou (?:sinon |bien )?|sauf si |à moins que )"
                               r"[A-ZÀ-ÖØ-Þ][a-zà-ÿ-]+\b")
PRONOUN = {"je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles", "qui", "cela",
           "ça", "chacun", "quelqu’un", "quelqu'un", "personne"}


def passages(segments):
    """Rattache chaque phrase aux bornes réellement disponibles dans Whisper."""
    parts, ids = [], []
    for index, segment in enumerate(segments):
        if ids and segment["start_ms"] - segments[ids[-1]]["end_ms"] > 1500:
            yield " ".join(parts), ids
            parts, ids = [], []
        for clause in re.findall(r"[^.!?…]+[.!?…]*", segment["text"]):
            if clause := clause.strip():
                parts.append(clause)
                ids.append(index)
                if clause.endswith((".", "!", "?", "…")):
                    yield " ".join(parts), ids
                    parts, ids = [], []
    if parts:
        yield " ".join(parts), ids


def analyze(transcription, file):
    segments = transcription["segments"]
    decisions, actions, context = [], [], []
    for quote, ids in passages(segments):
        point = {"text": quote, "source": {"file": file, "segment_indices": ids,
                 "start_ms": segments[ids[0]]["start_ms"], "end_ms": segments[ids[-1]]["end_ms"]},
                 "transcript_uncertain": any(segments[i]["uncertain"] for i in ids)}
        if quote.endswith("?") or TENTATIVE.search(quote):
            context.append(point)
        elif DECISION.match(quote):
            decisions.append(point)
        elif action := ACTION.match(quote):
            subject = action["subject"] or ""
            named = (subject.istitle() and subject.casefold() not in PRONOUN and " " not in subject
                     and not point["transcript_uncertain"] and not ALTERNATIVE_OWNER.search(quote))
            point["attribution"] = {"mentioned_owner": subject if named else None,
                                    "status": "named_in_passage" if named else "needs_review"}
            actions.append(point)
        else:
            context.append(point)
    # Un extrait de contexte, puis les conclusions prioritaires. Chaque entrée garde sa preuve.
    summary = context[:1] + decisions[:2] + actions[:2] if decisions or actions else context[:3]
    return {"engine": transcription["engine"], "execution": transcription["execution"],
            "status": transcription["status"], "duration_ms": transcription["duration_ms"],
            "segments": segments, "summary": summary, "decisions": decisions, "actions": actions}


def display(report):
    lines = []
    for key, title in (("summary", "Résumé"), ("decisions", "Décisions"), ("actions", "Actions")):
        lines.append(title)
        if not report[key]:
            lines.append("Aucun passage identifié.")
        for point in report[key]:
            source = point["source"]
            line = (f"[{source['file']} · {source['start_ms']/1000:.2f}–{source['end_ms']/1000:.2f} s] "
                    + point["text"])
            if point["transcript_uncertain"]:
                line += " [Transcription à vérifier]"
            if owner := point.get("attribution"):
                line += (f" [Responsable cité : {owner['mentioned_owner']}]" if owner["mentioned_owner"]
                         else " [Attribution à vérifier]")
            lines.append(line)
        lines.append("")
    return "\n".join(lines).strip()
