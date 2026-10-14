# LessonTrack

LessonTrack prepares weekly tutor reports and reminders from Google Sheets. It validates submissions, tracks revisions and delivery outcomes in an append-only Sheets journal, and can summarize reports with OpenAI. The public repository contains the current application code and synthetic tests.

## Set up

Use Python 3.12 on macOS or Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```

Set the values listed in [`env.example`](env.example) in your shell. A `.env` file is only a template until you load it; for example, use `set -a; source .env; set +a` in a trusted local shell. Keep the file out of Git. For Sheets authentication, set `SHEETS_CREDENTIALS_JSON` to the service account JSON content or set `SHEETS_CREDENTIALS_FILE` to a local JSON path. The default local path is `sheets_credentials.json` in the repository root. SMTP uses `GMAIL_APP_PASSWORD`; a local `gmail_token.json` can provide Gmail OAuth fallback. GitHub Actions reads the same values from repository secrets. See [operations](docs/OPERATIONS.md) for the required secret names.

## Preview and apply

```bash
python Sunday.py
python Monday.py
python -m lessontrack.cli remind --campaign friday
python Sunday.py --week 2026-10-12 --include-archives
```

A preview reads Sheets and writes local diagnostics. It does not send mail, write Sheets, or call OpenAI. Sunday defaults to the most recently completed week; reminders default to the current week. A week runs Monday through Sunday. The class date determines the report week, and the latest submission for a tutor and week takes precedence. Invalid answers and ambiguous submissions cause a nonzero exit and record source row references.

For an offline review, pass `--roster-csv path/to/roster.csv --responses-csv path/to/responses.csv`. CSV previews cannot apply. Store exports outside Git. Use `--output path/to/private-preview.txt` for a private text preview outside the diagnostics directory.

To write journal and roster updates and send mail, add `--apply` to `Sunday.py` or `Monday.py`. Review the preview and the opening balance procedure in [operations](docs/OPERATIONS.md) before the first report apply. Apply operations preserve original response rows and only update the roster columns owned by LessonTrack. Delivery states are recorded so a rerun does not blindly resend accepted or uncertain mail.

The GitHub Actions jobs run only when manually dispatched. Dispatches default to preview; `apply` must be selected explicitly. CI runs the synthetic test suite and lint on pushes and pull requests.

## Tests and diagnostics

```bash
python -m unittest discover -s tests -v
ruff check .
```

Tests use synthetic records and mock external services. Each command stores `events.jsonl` and `summary.json` under `.lessontrack/runs/<run-id>/`. Diagnostic records contain stage timings, source row references, error codes, and provider status/request IDs, while excluding contact details and report narratives. `test_email.py --send --recipient address@example.com` is an explicit delivery check. `student_pairing_email.py` accepts a private JSON file of pairings and requires `--send` to deliver.

## Code layout

| Module | Purpose |
| --- | --- |
| `lessontrack/settings.py` | Environment-based configuration |
| `lessontrack/reports.py` | Validation and weekly report selection |
| `lessontrack/storage.py` | Sheets access, event journal, and scoped roster writes |
| `lessontrack/ai.py` | Bounded summary generation and caching |
| `lessontrack/mail.py` | SMTP and Gmail delivery with outcome tracking |
| `lessontrack/jobs.py` | Report and reminder coordination |
| `lessontrack/diagnostics.py` | Safe run traces and error codes |
| `lessontrack/cli.py` | Preview and apply entrypoint |

`Monday.py`, `Sunday.py`, `Email.py`, and `ai_summary.py` provide compatibility entrypoints.
