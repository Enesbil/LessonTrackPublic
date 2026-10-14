"""Preview by default. Pass --apply to persist and send."""

from lessontrack.cli import main

if __name__ == "__main__":
    import sys

    raise SystemExit(main(["report", *sys.argv[1:]]))
