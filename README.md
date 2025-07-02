# LessonTrack: Automated Tutor Reporting and Management System

LessonTrack is a Python-based automation system designed to streamline tutor reporting, monitor tutor activity, and provide insightful summaries for management and school representatives. It leverages Google Sheets for data storage, Gmail API for email communication, and OpenAI's GPT models for intelligent summarization and safety-checking of tutor reports.

## Key Features

*   **Automated Weekly Reminders:** Sends email reminders to tutors every Monday to submit their weekly lesson reports via a Google Form.
*   **Form Response Processing:** Reads and processes tutor submissions from a Google Form linked to a Google Sheet.
*   **Cumulative Data Tracking:** Tracks total lessons, submissions, and hours for each tutor over time.
*   **Double-Counting Prevention:** Uses a "Last Processed Timestamp" to ensure that form responses are not processed multiple times if scripts are re-run.
*   **AI-Powered Summaries:**
    *   Generates concise summaries of each tutor's weekly report using OpenAI's `gpt-4o` model.
    *   Includes a **critical safety and conduct review** to flag any potentially inappropriate content, sexually suggestive language, grooming behaviors, or threats, quoting problematic statements under an "IMMEDIATE ATTENTION REQUIRED:" heading.
*   **Automated Weekly Reports:**
    *   **For School Representatives:** Sends tailored email summaries of their respective school's tutors.
    *   **For Management:** Sends a comprehensive weekly email report including:
        *   Overall statistics (Total Tutors, Active Tutors This Week, Total Hours This Week, Total Hours All Time).
        *   Detailed summaries for all tutors, grouped by school.
*   **Google Sheets Integration:**
    *   Reads tutor information, representative details, and form responses from designated Google Sheets.
    *   Updates a master "Tutor Info" Google Sheet with the latest cumulative data for each tutor after every weekly processing cycle.

## Quick Start

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd LessonTrackDeploymentCopy-main
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Follow the setup guide:**
   See [LessonTrack_SETUP_GUIDE.md](LessonTrack_SETUP_GUIDE.md) for detailed configuration instructions.

## Project Structure

```
LessonTrack/
├── .venv/                     # Virtual environment
├── __pycache__/
├── ai_summary.py              # Core logic for data loading, processing, AI summaries, GSheets updates
├── Email.py                   # Handles all email sending functionalities (reminders, reports)
├── Monday.py                  # Script to run on Mondays: sends form submission reminders to tutors
├── Sunday.py                  # Script to run on Sundays: processes forms, generates reports, sends emails
├── test_sunday_no_email.py    # For testing Sunday's logic without sending actual emails
├── test_email.py              # Basic script to test Gmail API email sending
├── requirements.txt           # Python dependencies
├── .env                       # Environment variables (create from env.example)
├── env.example                # Example environment configuration
├── SETUP.md                   # Detailed setup instructions
├── README.md                  # This file
└── .gitignore                 # Git ignore rules (excludes credential files)
```

## Configuration

All sensitive information is now managed through environment variables. You'll need to:

1. **Set up environment variables** (see `env.example`)
2. **Configure Google Cloud credentials** (see [LessonTrack_SETUP_GUIDE.md](LessonTrack_SETUP_GUIDE.md))
3. **Create and configure Google Sheets** (see [LessonTrack_SETUP_GUIDE.md](LessonTrack_SETUP_GUIDE.md))
4. **Set up OpenAI API access** (see [SETUP.md](LessonTrack_SETUP_GUIDE.md))

## Running the System

*   **To Send Monday Form Submission Reminders:**
    ```bash
    python Monday.py
    ```
    *(This will send emails to all tutors listed in the Tutor Info Sheet)*

*   **To Run Sunday Weekly Reporting and Emailing:**
    ```bash
    python Sunday.py
    ```
    *(This loads data, processes responses, updates the Tutor Info Sheet, generates AI summaries, and emails reports to representatives and management.)*

*   **To Test Sunday Logic Without Sending Emails:**
    ```bash
    python test_sunday_no_email.py
    ```
    *(This performs all data processing and AI summary generation, then prints the would-be email contents to the console.)*

*   **To Test Basic Email Functionality:**
    ```bash
    python test_email.py
    ```

## Key Scripts Overview

*   **`ai_summary.py`:**
    *   Handles loading tutor and representative data from Google Sheets.
    *   Fetches and processes new form responses.
    *   Manages cumulative data updates and prevents double-counting.
    *   Contains the `Tutor` and `Representative` classes.
    *   Interfaces with OpenAI API to generate summaries and conduct safety checks.
    *   Updates the Tutor Information Google Sheet.
*   **`Email.py`:**
    *   Manages Gmail API authentication and email sending.
    *   Contains functions to send various types of emails (reminders, representative reports, management reports).
    *   Orchestrates the data flow for generating weekly reports.
*   **`Monday.py`:** Simple script to trigger reminder emails via `Email.py`.
*   **`Sunday.py`:** Simple script to trigger the full weekly reporting process via `Email.py`.

## Data Flow (Sunday Process)

1.  `Sunday.py` calls `send_weekly_reports` in `Email.py`.
2.  `Email.py` calls functions in `ai_summary.py`:
    *   `load_tutors()`: Loads current tutor data from Google Sheet.
    *   `attach_lesson_reports_to_tutors()`: Fetches new form responses and updates tutor objects (weekly hours, cumulative totals, `last_processed_timestamp`).
    *   `save_tutors_to_google_sheet()`: Writes the updated tutor data (including new cumulative totals and timestamps) back to the Tutor Info Google Sheet.
    *   `generate_school_summaries()`: Iterates through tutors, calls `tutor.summarize_responses()` (which calls OpenAI API), and groups summaries by school.
    *   `load_representatives()`: Loads representative data.
3.  `Email.py` then formats and sends emails to representatives and management using the generated summaries and statistics.

## Security and Privacy

This repository is designed to be open source safe:

- **No hardcoded credentials** - All sensitive data uses environment variables
- **Credential files excluded** - `.gitignore` prevents accidental commits of sensitive files
- **Configurable URLs** - All Google Sheets and form URLs are configurable
- **Privacy-focused** - AI summaries exclude personal information

## Important Considerations

*   **API Keys & Credentials:** Keep your `.env` file, `gmail_credentials.json`, `gmail_token.json`, and `sheets_credentials.json` secure. Never commit these files to version control.
*   **Google Sheet Permissions:** Ensure the service account email has "Editor" access to all relevant Google Sheets.
*   **Google Form Structure:** The form response sheet needs a reliable "Tutor Name" column that matches names in the Tutor Info Sheet, and a "Timestamp" column.
*   **Cost Monitoring:** Be mindful of OpenAI API usage costs, especially with a large number of tutors or very long reports.
*   **Error Handling:** The system includes some error handling, but further enhancements can be added for more robustness in production.

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source. Please check the LICENSE file for details.

## Support

For setup help, see [SETUP.md](SETUP.md). For other questions, please create an issue in the repository.
