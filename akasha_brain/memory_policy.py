"""Classements déclarés pour la bibliothèque de compétences Notes."""

from .memory_workflows import WorkflowLibrary

CONTEXTUAL = "contextual"
FILTERED_SIMILARITY = "filtered_similarity"


class PolicyWorkflowLibrary(WorkflowLibrary):
    """Applique la version sélectionnée à la recherche et au rejeu du workflow."""

    def __init__(self, memory, version: str):
        if version not in (CONTEXTUAL, FILTERED_SIMILARITY):
            raise ValueError("Politique de classement mémoire inconnue.")
        super().__init__(memory)
        self.version = version

    def candidates(self, control, db, active, goal, catalog, context, *, replay_index=None):
        entries = super().candidates(control, db, active, goal, catalog, context, replay_index=replay_index)
        if self.version == FILTERED_SIMILARITY:
            for entry in entries:
                entry["score"] = entry["signals"]["relevance"]
        return entries
