"""Vérifie le lot G8 Qwen hors ligne dans Edge et consigne le résultat de l’export."""

import argparse
from base64 import b64decode
from hashlib import sha256
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from g8_blind_listening import CORPUS, LETTERS, RESULTS, write_json


def verify(public, results=RESULTS):
    lot = public.name.removeprefix("ecoute-")
    verification = results / f"g8-streaming-{lot}-verification.json"
    report = json.loads(verification.read_bytes())
    key = json.loads((results / f"g8-streaming-{lot}-cle.json").read_bytes())
    assert report["lot"] == key["lot"] == lot
    variants = {"reference", "nuance", "sobre"}
    order = key["ordre"]
    assert len(order) == 3 and all(len(row) == 3 and set(row) == variants for row in order)
    assert all(set(positions) == variants for positions in zip(*order))
    phrases = json.loads((CORPUS / "phrases.json").read_bytes())
    ids = [f"{n}-{letter}" for n in range(1, 4) for letter in LETTERS]
    assert {p.name for p in public.iterdir()} == {"ecoute.html", *(f"{i}.wav" for i in ids)}
    assert [clip["id"] for clip in report["clips"]] == ids

    with sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True, args=["--mute-audio", "--disable-gpu"])
        try:
            context = browser.new_context(offline=True, accept_downloads=True)
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto((public / "ecoute.html").resolve().as_uri())
            assert page.locator("section p").all_text_contents() == [f"« {p} »" for p in phrases]
            assert not any(word in page.locator("body").inner_text().casefold()
                           for word in ("qwen", "reference", "nuance", "sobre"))
            players = page.locator("audio")
            assert players.count() == len(ids)
            for player, clip in zip(players.all(), report["clips"], strict=True):
                contents = (public / f"{clip['id']}.wav").read_bytes()
                prefix, encoded = player.get_attribute("src").split(",", 1)
                assert prefix == "data:audio/wav;base64" and b64decode(encoded, validate=True) == contents
                assert sha256(contents).hexdigest() == clip["sha256"]
                player.evaluate("async a => { a.muted = true; await a.play() }")
                page.wait_for_function("() => [...document.querySelectorAll('audio')].some(a => !a.paused && a.currentTime > 0)")
                assert player.evaluate("a => a.muted && !a.paused && Number.isFinite(a.duration) && a.currentTime > 0")
                assert page.locator("audio").evaluate_all("xs => xs.filter(a => !a.paused).length") == 1
            players.last.evaluate("a => a.pause()")

            assert not page.locator("form").evaluate("f => f.checkValidity()")
            answers = []
            for n, choice in enumerate(("B", "Ex æquo", "Aucune"), 1):
                select = page.locator(f"#p{n}")
                assert select.locator("option").all_text_contents() == ["Choisir", *LETTERS, "Ex æquo", "Aucune"]
                select.select_option(choice)
                note = "Essai d’export, à écarter." if n == 2 else ""
                page.locator(f"#r{n}").fill(note)
                answers.append({"phrase": n, "choix": choice, "remarque": note})
            with page.expect_download() as pending:
                page.get_by_role("button", name="Enregistrer mes réponses").click()
            download = pending.value
            assert download.suggested_filename == f"ecoute-g8-{lot}-reponses.json"
            assert json.loads(download.path().read_bytes()) == {"lot": lot, "reponses": answers}
            assert not errors, errors
            report["navigateur"] = {"nom": "Edge", "version": browser.version, "hors_ligne": True,
                                    "sans_fenetre": True, "muet": True, "lectures_verifiees": len(ids),
                                    "export_verifie": download.suggested_filename}
        finally:
            browser.close()
    write_json(verification, report)
    print(verification)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("public", type=Path, help="Répertoire ecoute-<lot> à vérifier.")
    verify(parser.parse_args().public)
