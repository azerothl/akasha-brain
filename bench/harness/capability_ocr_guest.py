"""Qualification sur entrées synthétiques et lecture OCR dans le bac."""

from pathlib import Path
import shutil
import subprocess
import sys

RESULT_LIMIT = 96


def text(engine, image):
    import numpy as np

    rows, _ = engine(np.asarray(image.convert("RGB"))[:, :, ::-1].copy())
    return "\n".join(row[1] for row in (rows or ()))


def qualify(engine):
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 48)
    for expected in ("ATLAS 42", "COBALT 17"):
        image = Image.new("RGB", (580, 125), "white")
        ImageDraw.Draw(image).text((28, 26), expected, fill="black", font=font)
        assert " ".join(text(engine, image).upper().split()) == expected


def read_image(engine, path):
    from PIL import Image

    try:
        with Image.open(path, formats=("PNG", "JPEG")) as image:
            if image.width * image.height > 12_000_000 or getattr(image, "is_animated", False):
                return b"\x01"
            image.load()
            image = image.convert("RGB")
    except (OSError, ValueError, Image.DecompressionBombError):
        return b"\x01"
    encoded = text(engine, image).encode("utf-8")
    if len(encoded) > RESULT_LIMIT:
        return b"\x02" + encoded[:RESULT_LIMIT].decode("utf-8", errors="ignore").encode("utf-8")
    return b"\x00" + encoded


def run_worker():
    sys.path.insert(0, str(Path(__file__).parent / "ocr-packages"))
    from rapidocr_onnxruntime import RapidOCR

    engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)
    sessions = (engine.text_det.infer, engine.text_cls.infer, engine.text_rec.session)
    if any(session.session.get_providers() != ["CPUExecutionProvider"] for session in sessions):
        raise RuntimeError("Fournisseur OCR inattendu.")
    image_path = Path("image.input")
    if image_path.is_file():
        Path("ocr-result.bin").write_bytes(read_image(engine, image_path))
    else:
        qualify(engine)


def launch():
    source = Path(__file__)
    mount = Path(sys.executable).parent.parent
    local = Path.cwd() / "ocr-runtime"
    local.mkdir()
    for name in ("python", "ocr-packages"):
        shutil.copytree(mount / name, local / name)
    script = local / source.name
    shutil.copyfile(source, script)
    return subprocess.run([str(local / "python" / "python.exe"), "-I", "-B", "-X", "utf8", str(script), "--worker"]).returncode


if __name__ == "__main__":
    if sys.argv[1:] == ["--worker"]:
        run_worker()
    else:
        sys.exit(launch())
