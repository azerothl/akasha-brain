from akasha_brain.project_summary import summarize_project


def test_detailed_summary_follows_code_without_running_project(tmp_path):
    sources = {
        "README.md": "# Atlas\n\nAtlas organise les documents de travail par espace.\n",
        "tsconfig.json": '{"compilerOptions":{"paths":{"@/*":["./src/*"]}}}',
        "src/app/page.tsx": '''import { loadPages, PageList } from "@/lib/catalog";
export default async function Home() {
    const pages = await loadPages();
    return <PageList pages={pages} />;
}
''',
        "src/app/api/publish/route.ts": '''import { checkRequest } from "@/lib/guard";
import { publishPage, neverCalled } from "@/lib/catalog";
async function send(request: Request) {
    // neverCalled();
    const text = "neverCalled()";
    await publishPage(request);
    return Response.json({ ok: true }, { status: 201 });
}
export const POST = checkRequest(send);
''',
        "src/lib/guard.ts": '''import { currentUser } from "./auth";
export function checkRequest(handler: Function) {
    return async (request: Request) => {
        const user = await currentUser();
        if (!user) return Response.json({}, { status: 401 });
        return handler(request);
    };
}
''',
        "src/lib/catalog.ts": '''import { encrypt, database } from "./database";
import { writeFileSync } from "node:fs";
writeFileSync("ran-project.txt", "unexpected");
export async function publishPage(input: unknown) {
    await persist(input);
}
async function persist(input: unknown) {
    const db = database();
    db.transaction(() => encrypt(JSON.stringify(input)))();
}
''',
        "src/lib/database.ts": '''import Database from "better-sqlite3";
import { createCipheriv } from "node:crypto";
export function database() {
    return new Database("atlas.sqlite");
}
export function encrypt(value: string) {
    // createCipheriv("aes-128-gcm", key, nonce);
    return createCipheriv("aes-256-gcm", key, nonce).update(value);
}
''',
    }
    for name, content in sources.items():
        file = tmp_path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")

    assert "Parcours observés dans le code" not in summarize_project(tmp_path)
    detailed = summarize_project(tmp_path, detailed=True)
    assert "Page / · Home" in detailed and "[src/app/page.tsx:2]" in detailed and "PageList" in detailed
    assert "POST /api/publish · checkRequest enveloppe send" in detailed
    assert "publishPage()" in detailed and "neverCalled()" not in detailed
    assert "Statuts HTTP présents · 401" in detailed and "[src/lib/guard.ts:2]" in detailed
    assert "Écriture · persist" in detailed and "Utilise une transaction" in detailed
    assert "encrypt chiffre avec aes-256-gcm [src/lib/database.ts:6]" in detailed
    assert "aes-128-gcm" not in detailed and not (tmp_path / "ran-project.txt").exists()
