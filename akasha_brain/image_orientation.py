"""Sélection locale d'une rotation PNG à partir des indices visuels autorisés."""

from io import BytesIO

from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from .image_execution import ImageResult
from .planning import PlanningError
from .project import project_file, project_input

CAPABILITY = "image.orient"
# Ordre HG, HD, BD, BG. Permutations apprises dans learned-rotation-freeze-v1.
ROTATIONS = {0: (0, 1, 2, 3), 90: (3, 0, 1, 2), 180: (2, 3, 0, 1), 270: (1, 2, 3, 0)}


def read_png(project, name):
    from PIL import Image

    raw = project_input(project_file(project, name), byte_limit=8 * 1024 * 1024)
    try:
        opened = Image.open(BytesIO(raw), formats=["PNG"])
    except Image.DecompressionBombError as error:
        raise PlanningError(AkashaError(ErrorCode.RESOURCE_BUDGET_EXCEEDED, "PNG trop grand.")) from error
    with opened as image:
        if image.width * image.height > 1024 * 1024:
            raise PlanningError(AkashaError(ErrorCode.RESOURCE_BUDGET_EXCEEDED,
                                            "L’orientation accepte au maximum un mégapixel par image."))
        if image.is_animated or raw[24] > 8 or image.mode not in {"1", "L", "LA", "P", "RGB", "RGBA"}:
            raise ValueError("Indiquez un PNG fixe en couleurs ou niveaux de gris sur 8 bits.")
        pixels = image.convert("RGBA")
        pixels.info.clear()
        return pixels


def corners(image):
    right, bottom = image.width - 1, image.height - 1
    return tuple(image.getpixel(point) for point in ((0, 0), (right, 0), (right, bottom), (0, bottom)))


def rotate(image, degrees):
    from PIL import Image

    operations = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
    return image.transpose(operations[degrees]) if degrees else image


def abstain(message, **details):
    raise PlanningError(AkashaError(ErrorCode.CONTRACT_PRECONDITION_FAILED, message,
                                    {"capability": CAPABILITY, "outcome": "abstain", **details}))


def orient(project, inputs, *, corners_only):
    source = read_png(project, inputs[0])
    if len(inputs) == 1:
        abstain("Indiquez une image de référence pour déterminer l’orientation souhaitée.",
                evidence="no_target")
    reference = read_png(project, inputs[1])
    before, goal = corners(source), corners(reference)
    candidates = [angle for angle, order in ROTATIONS.items() if tuple(before[i] for i in order) == goal]
    proof = {"corner_candidates": candidates, "evidence": "corners"}
    if candidates and not corners_only:
        proof["evidence"] = "visual_pattern" if len(candidates) > 1 else "confirmed_corners"
        expected = reference.tobytes()
        matches = []
        for angle in candidates:
            view = rotate(source, angle)
            if view.size == reference.size and view.tobytes() == expected:
                matches.append(angle)
    else:
        matches = candidates
    proof["matching_rotations"] = matches
    if len(matches) != 1:
        abstain("Plusieurs rotations sont compatibles avec les indices fournis." if matches else
                "Aucune rotation ne correspond aux indices fournis.", **proof)
    stream = BytesIO()
    rotate(source, matches[0]).save(stream, format="PNG")
    return ImageResult(stream.getvalue(), {**proof, "clockwise_degrees": matches[0]})
