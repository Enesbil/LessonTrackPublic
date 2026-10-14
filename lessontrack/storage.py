"""Bounded Sheets operations and an append-only processing/delivery journal."""

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import time
from uuid import uuid4

from . import settings
from .diagnostics import Problem, event, stage
from .reports import digest, rows_from_values

EVENT_HEADERS = ["Event ID", "Kind", "Key", "Payload", "Recorded At"]


def make_client(credentials):
    import gspread
    from gspread.http_client import HTTPClient

    class TracedHTTPClient(HTTPClient):
        last_request = 0.0

        def request(self, method, *args, **kwargs):
            for attempt in range(1, 4):
                # Stay below the Sheets per-user minute quota even during large reminder batches.
                time.sleep(max(0, 1.25 - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                started = self.last_request
                try:
                    result = super().request(method, *args, **kwargs)
                except gspread.exceptions.APIError as exc:
                    status = exc.response.status_code
                    event(
                        "sheets_http_failed",
                        "WARNING",
                        http_status=status,
                        method=method,
                        attempt=attempt,
                        duration_ms=round((time.monotonic() - started) * 1000),
                    )
                    # A 429 explicitly rejects the operation. Only reads retry other transient failures.
                    if attempt < 3 and (
                        status == 429 or (method.lower() == "get" and status in {500, 502, 503, 504})
                    ):
                        time.sleep(2**attempt)
                        continue
                    raise
                event(
                    "sheets_http_completed",
                    http_status=result.status_code,
                    method=method,
                    attempt=attempt,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                return result

    return gspread.authorize(credentials, http_client=TracedHTTPClient)


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        return rows_from_values(list(csv.reader(f)), digest(Path(path).name)[:16])


class Sheets:
    def __init__(self, client=None):
        self.client = client
        self.books = {}

    def book(self, url):
        match = re.search(r"/d/([A-Za-z0-9_-]+)", url)
        if not match:
            raise Problem("invalid_sheet_url")
        key = match.group(1)
        if self.client is None:
            from google.oauth2.service_account import Credentials

            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            credentials_json = os.getenv("SHEETS_CREDENTIALS_JSON")
            if credentials_json:
                creds = Credentials.from_service_account_info(json.loads(credentials_json), scopes=scopes)
            else:
                credentials_file = os.getenv("SHEETS_CREDENTIALS_FILE", str(settings.ROOT / "sheets_credentials.json"))
                creds = Credentials.from_service_account_file(credentials_file, scopes=scopes)
            self.client = make_client(creds)
            self.client.set_timeout((10, 45))
        if key not in self.books:
            with stage("sheets_open", source=digest(key)[:16]):
                self.books[key] = self.client.open_by_key(key)
        return self.books[key]

    def worksheet(self, url, title=None):
        book = self.book(url)
        if title:
            return book.worksheet(title)
        gid = re.search(r"[?&#]gid=(\d+)", url)
        worksheet = book.get_worksheet_by_id(int(gid.group(1))) if gid else book.get_worksheet(0)
        if worksheet is None:
            raise Problem("worksheet_missing")
        return worksheet

    def read(self, url, title=None):
        with stage("sheets_read", source=digest(url)[:16]):
            worksheet = self.worksheet(url, title)
            values = worksheet.get_values(
                value_render_option="UNFORMATTED_VALUE", date_time_render_option="SERIAL_NUMBER"
            )
            headers, rows = rows_from_values(values, str(worksheet.id))
            event("sheet_read", source=str(worksheet.id), rows=len(rows), columns=len(headers))
            return headers, rows

    def response_timezone(self):
        metadata = self.book(settings.RESPONSE_CSV_URL).fetch_sheet_metadata(
            params={"fields": "properties.timeZone"}
        )
        return metadata["properties"]["timeZone"]

    def journal(self, writable=False):
        import gspread

        book = self.book(settings.TUTOR_INFO_CSV_URL)
        try:
            worksheet = book.worksheet(settings.STATE_TAB)
        except gspread.WorksheetNotFound:
            if not writable:
                return Journal()
            with stage("journal_create"):
                sheet_id = uuid4().int & 0x7FFFFFFF
                # Create the sheet and its header atomically, so a crash cannot leave a headerless journal.
                book.batch_update(
                    {
                        "requests": [
                            {
                                "addSheet": {
                                    "properties": {
                                        "sheetId": sheet_id,
                                        "title": settings.STATE_TAB,
                                        "gridProperties": {
                                            "rowCount": 1000,
                                            "columnCount": len(EVENT_HEADERS),
                                        },
                                    }
                                }
                            },
                            {
                                "updateCells": {
                                    "range": {
                                        "sheetId": sheet_id,
                                        "startRowIndex": 0,
                                        "endRowIndex": 1,
                                        "startColumnIndex": 0,
                                        "endColumnIndex": len(EVENT_HEADERS),
                                    },
                                    "rows": [
                                        {
                                            "values": [
                                                {"userEnteredValue": {"stringValue": x}}
                                                for x in EVENT_HEADERS
                                            ]
                                        }
                                    ],
                                    "fields": "userEnteredValue",
                                }
                            },
                        ]
                    }
                )
                worksheet = book.worksheet(settings.STATE_TAB)
        with stage("journal_read"):
            values = worksheet.get_all_values()
            if not values or values[0] != EVENT_HEADERS:
                raise Problem("journal_schema_invalid")
            entries = []
            for row in values[1:]:
                if not any(row):
                    continue
                if len(row) != len(EVENT_HEADERS):
                    raise Problem("journal_row_invalid")
                try:
                    payload = json.loads(row[3])
                except (ValueError, TypeError):
                    raise Problem("journal_payload_invalid") from None
                if row[0] != digest([row[1], row[2], payload]):
                    raise Problem("journal_integrity_failed")
                entries.append((row[1], row[2], payload))
        return Journal(entries, worksheet if writable else None)

    def update_roster(self, tutors, weekly, totals, report_week):
        """One RAW batch; preserves admin fields and rereads identity before addressing rows."""
        from gspread.utils import rowcol_to_a1

        worksheet = self.worksheet(settings.TUTOR_INFO_CSV_URL)
        values = worksheet.get_all_values()
        headers, rows = rows_from_values(values, str(worksheet.id))
        current = {str(r["values"].get("Tutor Name", "")).strip(): r for r in rows}
        if set(current) != set(tutors):
            raise Problem("roster_changed_during_run")
        owned = [
            "Total Hours",
            "Latest Weekly Hours",
            "Taught This Week",
            "Submitted This Week",
            "Reporting Week",
            "Last Processed Timestamp",
        ]
        new_headers = headers + [h for h in owned if h not in headers]
        updates = []
        if new_headers != headers:
            if len(new_headers) > worksheet.col_count:
                worksheet.add_cols(len(new_headers) - worksheet.col_count)
            updates.append({"range": "A1", "values": [new_headers]})
        for name, tutor in tutors.items():
            current_row = current[name]
            if str(current_row["values"].get("Email", "")).strip().lower() != tutor.email:
                raise Problem("roster_changed_during_run")
            report = weekly.get((tutor.id, report_week))
            output = {
                "Total Hours": float(totals[tutor.id]),
                "Latest Weekly Hours": float(report.hours) if report else "",
                "Taught This Week": ("yes" if report.taught else "no") if report else "",
                "Submitted This Week": "yes" if report else "no",
                "Reporting Week": str(report_week),
            }
            submitted = [r.submitted for (tid, week), r in weekly.items() if tid == tutor.id]
            if submitted:
                output["Last Processed Timestamp"] = max(submitted).isoformat()
            for key, value in output.items():
                updates.append(
                    {
                        "range": rowcol_to_a1(current_row["row"], new_headers.index(key) + 1),
                        "values": [[value]],
                    }
                )
        # Validate JSON before any value update. No clear() operation exists.
        json.dumps(updates, allow_nan=False)
        with stage("roster_update", rows=len(tutors)):
            worksheet.batch_update(updates, raw=True)


class Journal:
    def __init__(self, entries=(), worksheet=None):
        self.entries = list(entries)
        self.worksheet = worksheet
        self.ids = {digest([kind, key, payload]) for kind, key, payload in self.entries}

    def append(self, kind, key, payload):
        self.append_many([(kind, key, payload)])

    def append_many(self, entries):
        pending = []
        seen = set(self.ids)
        for kind, key, payload in entries:
            event_id = digest([kind, key, payload])
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if len(encoded) > 45000:
                raise Problem("journal_payload_too_large")
            if event_id in seen:
                continue
            seen.add(event_id)
            pending.append((event_id, kind, key, payload, encoded))
        if not pending:
            return
        if self.worksheet is not None:
            values = [
                [eid, kind, key, encoded, datetime.now(timezone.utc).isoformat()]
                for eid, kind, key, payload, encoded in pending
            ]
            with stage("journal_append", records=len(values)):
                # Do not blindly retry ambiguous append failures; the next run rereads event IDs.
                self.worksheet.append_rows(values, value_input_option="RAW")
        self.entries.extend((kind, key, payload) for eid, kind, key, payload, encoded in pending)
        self.ids.update(eid for eid, kind, key, payload, encoded in pending)

    def latest(self, kind):
        return {key: payload for entry_kind, key, payload in self.entries if entry_kind == kind}
