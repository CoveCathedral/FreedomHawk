"""Launch the Firehawk Accessible Controller UI:  python -m firehawk"""

from __future__ import annotations


def main() -> int:
    from .ui import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
