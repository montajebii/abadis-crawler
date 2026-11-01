"""Entry point: python -m crawler"""
import sys


def _main() -> int:
    try:
        from crawler.cli import main
    except ImportError:
        print(
            "cli.py is not implemented yet. This will be added in a future step.",
            file=sys.stderr,
        )
        return 1
    return main()


if __name__ == "__main__":
    sys.exit(_main())
