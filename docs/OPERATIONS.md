# Operations and recovery

## Configure a run

Set the following values as environment variables locally or as GitHub Actions repository secrets: `TUTOR_INFO_CSV_URL`, `RESPONSE_CSV_URL`, `REPRESENTATIVE_CSV_URL`, `FORM_URL`, `DRIVE_FOLDER_URL`, `SENDER_EMAIL`, `MANAGEMENT_EMAILS`, `OPENAI_API_KEY`, and `GMAIL_APP_PASSWORD`. Set `SHEETS_CREDENTIALS_JSON` to the service account JSON for Actions. Locally, `SHEETS_CREDENTIALS_FILE` may point to a private file instead. A local Gmail OAuth fallback may read `GMAIL_TOKEN_FILE` or `gmail_token.json`; the token can refresh without opening a browser.

Do not add credential files, response exports, or local pairing lists to the repository. The workflow jobs are manual and default to read-only preview. Use one designated environment for apply operations to avoid concurrent writers.

## Inspect a failure

Open the run summary and its diagnostic artifact. Search `events.jsonl` for `stage_failed`, `response_rejected`, `recipient_delivery_failed`, or `run_failed`. Source worksheet IDs and row numbers identify bad input; tutor and recipient references are hashes. Provider request IDs and bounded error codes help diagnose API failures. Diagnostics deliberately omit credential values and response narratives.

A report week runs Monday to Sunday and comes from class date. A January 1 no-teaching placeholder with zero hours uses the submission week in the response spreadsheet's timezone; a late placeholder may need manual reconciliation. Conflicting answers, unknown tutors, and tied latest submissions require review. The application never treats a provider failure as an empty sheet.

## First apply and historical balances

Before the first report apply, review the roster's existing total hours and choose an opening Monday. Create a private JSON file containing every existing tutor's opening balance:

```json
{
  "start_week": "2026-01-05",
  "hours": {"internal-tutor-id": "10.5"}
}
```

Use the optional `Tutor ID` roster column for stable identities; otherwise the application uses a hash of the trimmed tutor name. Preview with `python Sunday.py --baseline-json path/to/opening-balance.json`. After reconciling historical responses and totals, use `python Sunday.py --apply --baseline-json path/to/opening-balance.json`. The first apply records the baseline in the journal. A later baseline cannot silently replace it. Avoid `--include-archives` in routine runs unless reviewing old response tabs.

The application updates only `Total Hours`, `Latest Weekly Hours`, `Taught This Week`, `Submitted This Week`, `Reporting Week`, and `Last Processed Timestamp`. It preserves other roster fields and the source responses.

## Delivery outcomes

A pending event is recorded before mail is sent. Accepted deliveries are skipped on rerun; rejected deliveries can retry. Pending or uncertain deliveries require review before resending because provider acceptance may have occurred. SMTP is primary. A local Gmail OAuth token can serve as fallback after a confirmed rejection or authentication failure. A lost connection during sending is uncertain and does not trigger fallback.

There is no transaction spanning Sheets and mail. If a process crashes after provider acceptance but before recording the result, inspect provider sent mail and the journal before taking further action. Successful AI summaries are cached by report revision. Report text is never written to the diagnostic artifact.

## Dependencies and checks

`pyproject.toml` declares dependencies; `uv.lock` and the two requirements files pin package versions and hashes. After dependency changes, regenerate exports with `uv lock` and `uv export`, then run the synthetic test suite and lint. Actions installs from the hashed requirements files, verifies the code, and uploads only `.lessontrack/runs/` diagnostics.
