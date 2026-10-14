"""Compatibility import surface for the reporting application.

Use Sunday.py or lessontrack.cli for previews/reporting. The old mutable-counter
and full-sheet replacement implementation has been replaced, not kept as a second
operational path. Runtime configuration is provided through the environment.
"""

from lessontrack.settings import OPENAI_API_KEY, TUTOR_INFO_CSV_URL, RESPONSE_CSV_URL, REPRESENTATIVE_CSV_URL
from lessontrack.storage import Sheets
from lessontrack.reports import Tutor, load_roster
from lessontrack.jobs import representatives

__all__ = [
    "OPENAI_API_KEY",
    "TUTOR_INFO_CSV_URL",
    "RESPONSE_CSV_URL",
    "REPRESENTATIVE_CSV_URL",
    "Tutor",
    "load_tutors",
    "load_representatives",
]


def load_tutors():
    _, rows = Sheets().read(TUTOR_INFO_CSV_URL)
    return list(load_roster(rows).values())


def load_representatives():
    _, rows = Sheets().read(REPRESENTATIVE_CSV_URL)
    return representatives(rows)


if __name__ == "__main__":
    import sys
    from lessontrack.cli import main

    raise SystemExit(main(["report", *sys.argv[1:]]))
