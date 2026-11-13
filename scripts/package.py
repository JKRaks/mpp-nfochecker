"""Build deterministic plugin ZIPs after the independent validation step."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = {"NfoCheck": "nfocheck"}


def build(name):
    directory = PLUGINS[name]
    plugin = ROOT / "plugins.v3" / directory
    version = json.loads((ROOT / "package.v3.json").read_text())[name]["version"]
    meta = plugin / "dist/assets/build-meta.json"
    if not (plugin / "dist/assets/remoteEntry.js").is_file() or not meta.is_file():
        raise SystemExit(f"{name} 缺少前端产物；请先在 frontend 执行 npm ci && npm run build")
    data = json.loads(meta.read_text())
    if data.get("version") != version or data.get("plugin") != name:
        raise SystemExit(f"{name} 前端产物不是当前插件/版本，请重新构建后打包")
    output = ROOT / "artifacts" / f"{name}-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    files = {f"{directory}/{p.relative_to(plugin)}": p for p in plugin.rglob("*.py") if "__pycache__" not in p.parts}
    files[f"{directory}/requirements.txt"] = plugin / "requirements.txt"
    files.update({f"{directory}/{p.relative_to(plugin)}": p for p in (plugin / "dist/assets").rglob("*") if p.is_file()})
    for filename in ("README.md", "TESTING.md", "PROVIDERS.md"):
        path = plugin / filename
        if not path.exists(): path = ROOT / filename
        if path.is_file(): files[f"{directory}/{filename}"] = path
    files[f"{directory}/TRANSLATION_TESTING.md"] = ROOT / "TRANSLATION_TESTING.md"
    for path in (ROOT / "examples").glob("*.json"):
        files[f"{directory}/examples/{path.name}"] = path
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for filename, path in sorted(files.items()):
            info = ZipInfo(filename, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{checksum}  {output.name}\n")
    print(f"{output} ({output.stat().st_size} bytes)\nSHA256 {checksum}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin", choices=[*PLUGINS, "all"], default="all")
    args = parser.parse_args()
    for name in (PLUGINS if args.plugin == "all" else [args.plugin]):
        build(name)
