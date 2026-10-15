"""Package source only; explicitly exclude credentials, databases, build caches and SDKs."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
dist.mkdir(exist_ok=True)
archive = dist / "personal-agent-v0.6-source.zip"
exclude_dirs = {"build", ".gradle", ".kotlin", "__pycache__", ".pytest_cache", ".ruff_cache"}
with ZipFile(archive, "w", ZIP_DEFLATED) as out:
    for base in ["backend", "android", "scripts", "docs", "spec", "deploy", ".github"]:
        for path in (root / base).rglob("*"):
            rel = path.relative_to(root)
            if not path.is_file() or any(part in exclude_dirs or part.endswith('.egg-info') for part in rel.parts):
                continue
            if path.name in {".env", "local.properties"} or path.name.startswith("agent.db") or path.suffix in {".pyc", ".apk"}:
                continue
            out.write(path, Path("personal-agent") / rel)
    for name in ["README.md", ".gitignore", ".dockerignore"]:
        out.write(root / name, Path("personal-agent") / name)
with ZipFile(archive) as packaged:
    assert not any(name.endswith('/.env') or '.db' in name or 'local.properties' in name for name in packaged.namelist())
print(archive)
