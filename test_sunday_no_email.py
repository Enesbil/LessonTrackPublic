"""Compatibility command for a genuinely read-only report preview."""

__test__ = False

if __name__ == "__main__":
    import sys
    from lessontrack.cli import main

    if "--apply" in sys.argv:
        raise SystemExit("This command cannot write or send. Use Sunday.py --apply deliberately.")
    raise SystemExit(main(["report", *sys.argv[1:]]))
