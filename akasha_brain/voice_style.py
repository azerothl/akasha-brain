"""Directions de lecture de Vivian retenues à l’écoute des réponses françaises."""

STYLES = {
    "reference": "Parle en français sur un ton conversationnel naturel. Fais entendre les questions, "
                 "marque clairement les corrections et garde un débit posé pour la narration.",
    "sobre": "Français parlé de France, voix tranquille, directe et complice. Démarre sans hésiter. "
             "Pour une question, attends réellement une réponse : termine sur une montée nette et brève. "
             "Pour une information, garde une mélodie discrète et descendante, sans emphase ni effet de scène.",
}


def reply_style(text, narration_only=False):
    if narration_only and "?" not in text and "？" not in text:
        return "sobre"
    return "reference"
