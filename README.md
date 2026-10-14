# LessonTrack

LessonTrack prepares weekly tutor reports and reminders from Google Sheets. It validates submissions, tracks revisions and delivery outcomes in an append-only Sheets journal, and summarizes reports with OpenAI when a report is applied. Run it from the Python CLI or the manual GitHub Actions workflows.

## Install and configure

Use Python 3.12 on macOS or Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt
```

Copy [`env.example`](env.example) to `.env`, replace its placeholders, and load it before running commands:

```bash
cp env.example .env
# Edit .env with your own values, then:
set -a
source .env
set +a
```

The file is ignored by Git and is not loaded automatically by the application. Separate multiple `MANAGEMENT_EMAILS` with commas. The Sheets service account needs access to the spreadsheets. Locally, point `SHEETS_CREDENTIALS_FILE` to its JSON file; the default is `sheets_credentials.json` in the repository root. SMTP uses `GMAIL_APP_PASSWORD`. A local Gmail OAuth token can provide fallback through `GMAIL_TOKEN_FILE` or `gmail_token.json`.

For GitHub Actions, configure `TUTOR_INFO_CSV_URL`, `RESPONSE_CSV_URL`, `REPRESENTATIVE_CSV_URL`, `FORM_URL`, `DRIVE_FOLDER_URL`, `SENDER_EMAIL`, `MANAGEMENT_EMAILS`, `OPENAI_API_KEY`, `GMAIL_APP_PASSWORD`, and `SHEETS_CREDENTIALS_JSON` as repository secrets. The last value is the service account JSON content. See [operations](docs/OPERATIONS.md) for the first apply procedure.

## Preview reports and reminders

```bash
python Sunday.py
python Monday.py
python -m lessontrack.cli remind --campaign friday
python Sunday.py --week 2026-10-12 --include-archives
```

A normal preview reads Sheets and writes local diagnostics. It does not send mail, write Sheets, or call OpenAI. `Sunday.py` selects the week ending on the most recent Sunday; reminders select the current Monday–Sunday week. Pass `--week YYYY-MM-DD` with any date in the desired week. `--include-archives` includes archived response tabs for review.

The class date determines a report's week. A no-teaching January 1 placeholder from 2025 or 2026 with zero hours uses the submission week instead. The latest submission for a tutor and week takes precedence. Invalid answers and ambiguous submissions cause a nonzero exit and record source row references.

For an offline report review, pass `--roster-csv path/to/roster.csv --responses-csv path/to/responses.csv`. This needs no Sheets access and cannot apply changes. Store exports outside Git. Use `--output .lessontrack/private-preview.txt` for a private text preview outside the diagnostics directory; `.lessontrack/` is ignored by Git.

## Apply results

```bash
python Sunday.py --apply --week 2026-10-12
python Monday.py --apply
python -m lessontrack.cli remind --campaign friday --apply
```

`Sunday.py --apply` records reports and opening balances in the journal, updates only LessonTrack-owned roster columns, generates summaries, and sends representative and management emails. A report apply requires a reviewed opening balance already in the journal or supplied with `--baseline-json`; follow [operations](docs/OPERATIONS.md) before running it. `Monday.py --apply` and the Friday command send tutor reminders. Delivery states are recorded so reruns do not blindly resend accepted or uncertain mail. Original response rows remain in Sheets.

The Monday, Sunday, and Friday GitHub Actions jobs run only when manually dispatched. Dispatches default to preview; select `apply` explicitly to write or send. CI runs the synthetic test suite and lint on pushes and pull requests.

## Tests and diagnostics

```bash
python -m unittest discover -s tests -v
ruff check .
```

Tests use synthetic records and mock external services. Each command stores `events.jsonl` and `summary.json` under `.lessontrack/runs/<run-id>/`. Diagnostic records contain stage timings, source row references, error codes, and provider status/request IDs, while excluding contact details and report narratives.

For an explicit email delivery check, run `python test_email.py --send --recipient address@example.com`. To preview a private pairing list, run `python student_pairing_email.py --pairings-json path/to/pairings.json`; add `--send` only when ready to deliver it. The pairing file must be a JSON list with `tutor_name`, `tutor_email`, `student_name`, `student_email`, and `student_phone` strings for each entry. Keep it outside Git.

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
