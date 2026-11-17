"""Lance le moteur hors ligne et présente sa sortie sur une surface balisée."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tkinter as tk


def start():
    script = Path(__file__)
    source = Path(sys.executable).parent
    runtime = Path.cwd().parent / "python-local"
    shutil.copytree(source, runtime)
    environment = {**os.environ, "TCL_LIBRARY": str(runtime / "tcl8.6"), "TK_LIBRARY": str(runtime / "tk8.6")}
    subprocess.Popen([str(runtime / "pythonw.exe"), "-I", "-B", str(script), "--worker", str(source.parent)],
                     env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def generate(mount):
    settings = json.loads(Path("image-request.json").read_bytes())
    binaries = Path.cwd().parent / "generator"
    shutil.copytree(mount / "engine", binaries)
    engine = binaries / "sd-cli.exe"
    target = Path.cwd() / "generated.png"
    with Path("image-engine.log").open("wb") as log:
        result = subprocess.run([
            str(engine), "-m", str(mount / "image-model.gguf"), "-p", settings["prompt"],
            "--steps", "4", "--cfg-scale", "1.0", "--sampling-method", "euler_a",
            "-W", "512", "-H", "512", "-t", "8", "--seed", "3927", "-o", str(target),
        ], cwd=binaries, stdout=log, stderr=subprocess.STDOUT, timeout=540)
    if result.returncode != 0 or not 1 <= target.stat().st_size <= 2 * 1024**2:
        raise RuntimeError(f"Sortie du moteur invalide, code 0x{result.returncode & 0xffffffff:08x}.")
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.geometry("544x544+12+12")
    image = tk.PhotoImage(master=root, file=str(target), format="png")
    if (image.width(), image.height()) != (512, 512):
        raise ValueError("Dimensions de l’image générée inattendues.")
    colors = {image.get(x, y) for x in range(0, 512, 32) for y in range(0, 512, 32)}
    if len(colors) < 24:
        raise ValueError("L’image générée est vide ou uniforme.")
    canvas = tk.Canvas(root, width=544, height=544, highlightthickness=0, bg=settings["frame"])
    canvas.pack()
    canvas.create_image(16, 16, anchor="nw", image=image)
    root.update()
    Path("image-status.txt").write_text("ready", encoding="ascii")
    root.mainloop()


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        try:
            generate(Path(sys.argv[2]))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, tk.TclError):
            Path("image-status.txt").write_text("failed", encoding="ascii")
    else:
        start()
