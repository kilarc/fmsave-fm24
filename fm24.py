"""FM24 entry point using the bundled, edition-aware fmsave source."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "dump":
        from fm_extract24 import main as dump_main

        return dump_main(sys.argv[2:])
    from fmsave.cli import main as fmsave_main

    return fmsave_main()


if __name__ == "__main__":
    raise SystemExit(main())
