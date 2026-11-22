"""Build the self-contained FM24 CSV launcher with the local fmsave source."""

import argparse
import base64
import io
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    output = parser.parse_args().output
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        for path in sorted((ROOT / "src/fmsave").rglob("*")):
            if not path.is_file() or (
                path.suffix not in (".py", ".json") and path.name != "py.typed"
            ):
                continue
            item = zipfile.ZipInfo(path.relative_to(ROOT / "src").as_posix())
            archive.writestr(item, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
    encoded = base64.b64encode(payload.getvalue()).decode("ascii")
    template = (ROOT / "scripts/launcher.cmd.in").read_text(encoding="utf-8")
    if template.count("@@PACKAGE_BASE64@@") != 1:
        raise ValueError("Invalid launcher template")
    script = template.replace("@@PACKAGE_BASE64@@", "\n".join(textwrap.wrap(encoded, 100)))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(script, encoding="utf-8", newline="\r\n")


if __name__ == "__main__":
    main()
