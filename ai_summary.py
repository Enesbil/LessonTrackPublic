import pandas as pd
import requests
import re
import os
from google.oauth2.service_account import Credentials
import gspread
from dotenv import load_dotenv

load_dotenv()

def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("sheets_credentials.json", scopes=scopes)
    return gspread.authorize(creds)

# pull variables from env file
TUTOR_INFO_CSV_URL = os.getenv("TUTOR_INFO_CSV_URL")
RESPONSE_CSV_URL = os.getenv("RESPONSE_CSV_URL")
REPRESENTATIVE_CSV_URL = os.getenv("REPRESENTATIVE_CSV_URL")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

required_env_vars = {
    "TUTOR_INFO_CSV_URL": TUTOR_INFO_CSV_URL,
    "RESPONSE_CSV_URL": RESPONSE_CSV_URL,
    "REPRESENTATIVE_CSV_URL": REPRESENTATIVE_CSV_URL,
    "OPENAI_API_KEY": OPENAI_API_KEY
}

missing_vars = [var for var, value in required_env_vars.items() if not value]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}. Please check your .env file or environment configuration.")

def fetch_csv(sheet_url):
    try:
        gc = get_gspread_client()

        match_id = re.search(r'/d/([a-zA-Z0-9-_]+)', sheet_url)
        if not match_id:
            print(f"Error: Could not parse Sheet ID from URL: {sheet_url}")
            return pd.DataFrame()
        sheet_id = match_id.group(1)

        spreadsheet = gc.open_by_key(sheet_id)

        worksheet = None
        match_gid = re.search(r'[#&]gid=([0-9]+)', sheet_url)
        if match_gid:
            gid = int(match_gid.group(1))
            try:
                worksheet = spreadsheet.get_worksheet_by_id(gid)
                if not worksheet:
                    print(f"Warning: Worksheet with GID {gid} not found by ID for URL {sheet_url}. Falling back to the first sheet.")
            except Exception as e_gid:
                print(f"Warning: Error trying to get worksheet by GID {gid} for URL {sheet_url}: {e_gid}. Falling back to the first sheet.")
        
        if not worksheet:
            worksheet = spreadsheet.sheet1

        if not worksheet:
            print(f"Error: Could not open or find a valid worksheet for URL: {sheet_url}")
            return pd.DataFrame()

        print(f"Successfully opened worksheet '{worksheet.title}' (ID: {worksheet.id}) from sheet '{spreadsheet.title}' using service account.")
        values = worksheet.get_all_values()

        if not values:
            print(f"No data found in sheet: {worksheet.title} from URL: {sheet_url}")
            return pd.DataFrame()
        
        header = [str(col).strip() if col is not None else '' for col in values[0]]
        
        if len(values) > 1:
            df = pd.DataFrame(values[1:], columns=header)
        else:
            df = pd.DataFrame(columns=header)
            
        return df
    except gspread.exceptions.APIError as e:
        print(f"gspread API Error fetching sheet data from '{sheet_url}': {e}")
        if hasattr(e, 'response') and e.response.status_code == 403:
            print("CRITICAL: This is likely a permissions issue. Ensure the service account email (from sheets_credentials.json) has at least 'Viewer' access to this Google Sheet.")
        elif hasattr(e, 'response') and e.response.status_code == 404:
            print(f"CRITICAL: Google Sheet not found for ID '{sheet_id}'. Please check the URL: {sheet_url}")
        return pd.DataFrame()
    except Exception as e:
        print(f"An unexpected error occurred fetching data from sheet '{sheet_url}': {e}")
        return pd.DataFrame()

# Tutor Class
class Tutor:
    def __init__(self, lesson_count=0, submission_count=0, name="NA", school="NA", grad="NA", email="NA", phone="NA", total_hours=0, weekly_hours=0, last_processed_timestamp=None):
        self.name = name
        self.school = school
        self.grad = grad
        self.email = email
        self.phone = phone
        self.lesson_count = lesson_count
        self.submission_count = submission_count
        self.total_hours = total_hours
        self.weekly_hours = weekly_hours
        self.google_form_responses = {}
        self.weekly_updates = {}
        self.last_processed_timestamp = pd.to_datetime(last_processed_timestamp, errors='coerce') # Ensure it's a datetime or NaT

    def __str__(self):
        return (
            f"Name: {self.name}\n"
            f"School: {self.school}\n"
            f"Graduation Year: {self.grad}\n"
            f"Email: {self.email}\n"
            f"Phone: {self.phone}\n"
            f"Lesson Count: {self.lesson_count}\n"
            f"Submission Count: {self.submission_count}\n"
        )
    
    # setters
    def update_lesson_count(self):
        self.lesson_count += 1

    def update_submission_count(self):
        self.submission_count += 1

    def custom_update_lesson_count(self, num):
        self.lesson_count += num

    def custom_update_submission_count(self, num):
        self.submission_count += num

    def update_hours(self, num):
        self.total_hours += num

    # extracts weekly responses for each student from the responses google sheet
    def get_responses(self, df_responses, response_name_column):
        if response_name_column in df_responses.columns:
            
            matches = df_responses[df_responses[response_name_column].astype(str).str.strip() == str(self.name).strip()]

            if not matches.empty:
                latest_form = matches.iloc[-1].copy()
                updates = {}
                updates["submitted_this_week"] = "yes"

                form_timestamp_str = latest_form.get("Timestamp")
                form_timestamp = pd.to_datetime(form_timestamp_str, errors='coerce')
                
                is_new_submission_for_cumulative_update = False
                if pd.isna(self.last_processed_timestamp):
                    if pd.notna(form_timestamp):
                        is_new_submission_for_cumulative_update = True
                elif pd.notna(form_timestamp) and form_timestamp > self.last_processed_timestamp:
                    is_new_submission_for_cumulative_update = True

                if is_new_submission_for_cumulative_update:
                    print(f"Processing NEW submission for {self.name} (Timestamp: {form_timestamp_str}) for cumulative updates.")
                    self.update_submission_count()
                    
                    taught_field = next((k for k in latest_form.index if "tutor" in k.lower() and "this" in k.lower()), None)
                    if taught_field:
                        taught_raw = latest_form[taught_field]
                        taught = str(taught_raw).strip().lower()
                        updates["taught_lessons"] = taught
                        if taught == "yes":
                            self.update_lesson_count()
                    
                    hours_field = next((k for k in latest_form.index if "hour" in k.lower()), None)
                    if hours_field:
                        try:
                            hours = float(latest_form[hours_field])
                            self.update_hours(hours) 
                            updates["weekly_hours"] = hours
                        except (ValueError, TypeError):
                            updates["weekly_hours"] = "Invalid"
                    self.last_processed_timestamp = form_timestamp 
                else:
                    print(f"Submission for {self.name} (Timestamp: {form_timestamp_str}) already processed or timestamp error. Not updating cumulative totals.")
                    
                    taught_field = next((k for k in latest_form.index if "tutor" in k.lower() and "this" in k.lower()), None)
                    if taught_field:
                        updates["taught_lessons"] = str(latest_form[taught_field]).strip().lower()
                    hours_field = next((k for k in latest_form.index if "hour" in k.lower()), None)
                    if hours_field:
                        try:
                            updates["weekly_hours"] = float(latest_form[hours_field])
                        except (ValueError, TypeError):
                            updates["weekly_hours"] = "Invalid"
                
                
                self.weekly_hours = updates.get("weekly_hours", 0.0) 
                if isinstance(self.weekly_hours, str): self.weekly_hours = 0.0

                print(f"{self.name} submission count is now {self.submission_count}")
                print(f"{self.name} lesson count is now {self.lesson_count}")
                print(f"{self.name} total hours is now {self.total_hours}")
                self.google_form_responses = latest_form.to_dict()
                self.weekly_updates = updates
                print(f"Updates for {self.name}: {self.weekly_updates}\n")
            else:
                print(f"No responses found for {self.name}\n")
                self.weekly_updates["submitted_this_week"] = "no"
                self.weekly_hours = 0.0 
        else:
            print(f"Missing column: '{response_name_column}'\n")
            self.weekly_hours = 0.0 

    def summarize_responses(self):
        if not self.google_form_responses:
            return "No responses to summarize"

        try:
            response_text = ""
            
            response_items = list(self.google_form_responses.items())
            for key, value in response_items[1:]:  
                if isinstance(value, str) and value.strip():
                    response_text += f"{key.strip()}: {value.strip()}\n"

            # prompt to generate summary
            prompt = (
                f"Instructions for AI:\\n"
                f"You are processing reports for an ENGLISH LANGUAGE TUTORING program. All summaries must be about English language learning activities. If the original content mentions other subjects or activities, creatively interpret and reframe them in terms of English language learning opportunities.\\n\\n"
                f"Your response will consist of two parts. \\n"
                f"Part 1: Generate a concise 1-2 sentence summary of the tutor's ENGLISH LANGUAGE LESSON activities and future plans. This summary should appear first and should NOT have any specific header. Focus on English language skills (reading, writing, speaking, listening, grammar, vocabulary, etc.). If the original content wasn't English-focused, suggest how it could be adapted for English learning or what English skills were practiced.\\n"
                f"Part 2: After the activity summary, perform a CRITICAL SAFETY AND CONDUCT REVIEW based on the 'Tutor's Full Report' below. Analyze it for ANY of the following specific categories of problematic content:\\n"
                f"   a. Sexually suggestive or explicit statements, or requests for inappropriate images/actions.\\n"
                f"   b. Grooming behaviors or overly personal/secretive relationship building.\\n"
                f"   c. Mentions of nudity or private body parts in a non-clinical, inappropriate context.\\n"
                f"   d. Expressions of intent to harm, bullying, or direct threats to a student's physical or emotional well-being.\\n"
                f"   e. Other language or described actions that are clearly unprofessional, unethical, or indicate a direct risk to student safety or welfare.\\n\\n"
                f"   IMPORTANT: Differentiate between these categories and legitimate academic discussion of sensitive topics (e.g., history, literature, social issues). Standard academic discussions are NOT to be flagged unless they cross into the problematic categories listed.\\n\\n"
                f"   If content matching ANY of the categories (a-e) is found, YOU MUST quote the exact problematic statement(s) directly under the heading 'IMMEDIATE ATTENTION REQUIRED:'. This heading and quoted statement(s) should appear after the activity summary from Part 1.\\n"
                f"   The activity summary (Part 1) MUST ALWAYS be present in your response, regardless of whether safety concerns are found in Part 2.\\n"
                f"   If, after careful review, no content from the specific categories (a-e) is found for Part 2, DO NOT add the 'IMMEDIATE ATTENTION REQUIRED:' section and DO NOT mention the absence of issues. In this case, your response will only contain the activity summary from Part 1.\\n\\n"
                f"Tutor's Full Report:\\n{response_text}"
            )

            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_API_KEY}"
            }
            data = {
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": "You are an AI assistant processing reports for an ENGLISH LANGUAGE TUTORING program. All summaries must focus on English language learning activities (reading, writing, speaking, listening, grammar, vocabulary, literature, etc.). If the original content mentions other subjects, interpret and reframe it in terms of English language learning. Your response must always start with a concise 1-2 sentence summary of English lesson activities/plans (without any header). Following this, if your CRITICAL SAFETY AND CONDUCT REVIEW identifies specific inappropriate content or safety threats, quote them under the specific heading 'IMMEDIATE ATTENTION REQUIRED:'. This safety section is conditional. The initial English activity summary is mandatory. Do not flag legitimate academic discussions of sensitive topics unless they meet the defined problematic criteria. If no safety issues are found, only provide the English activity summary."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.3, 
                "max_tokens": 300
            }

            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            ai_response_content = response.json()["choices"][0]["message"]["content"].strip()
            
            if "IMMEDIATE ATTENTION REQUIRED:" in ai_response_content:
                print(f"ALERT: Potential safety/conduct concern identified for tutor {self.name}.")
            
            return ai_response_content

        except Exception as e:
            print(f"--> Error summarizing for {self.name}: {e}")
            return f"Submissions: {self.submission_count}, Lessons: {self.lesson_count}, Weekly Hours: {self.weekly_hours}. Review full report for details; AI summary failed."

# Representative Class
class Representative:
    def __init__(self, name="NA", school="NA", email="NA", phone="NA"):
        self.name = name
        self.school = school
        self.email = email
        self.phone = phone

    def __str__(self):
        return (
            f"Name: {self.name}\n"
            f"School: {self.school}\n"
            f"Email: {self.email}\n"
            f"Phone: {self.phone}\n"
        )
     
DEFAULT_REPS = [
    Representative("Test Rep 1", "UF", "test1@example.com", "123456789"),
    Representative("Test Rep 2", "Mostar", "test2@example.com", "123456789"),
    Representative("Test Rep 3", "RBC", "test3@example.com", "123456789"),
]
REQUIRED_SCHOOLS = {"UF", "Mostar", "RBC"}

def load_tutors():
    df = fetch_csv(TUTOR_INFO_CSV_URL)
    print("\nTutor Info CSV Columns:", df.columns.tolist())

    # extract all tutors from tutors google sheet
    tutors = []
    for _, row in df.iterrows():
        
        raw_lessons = row.get("Total Lessons", 0)
        lesson_count = int(raw_lessons) if str(raw_lessons).strip() else 0

        raw_submissions = row.get("Total Submissions", 0)
        submission_count = int(raw_submissions) if str(raw_submissions).strip() else 0

        raw_hours = row.get("Total Hours", 0.0)
        total_hours = float(raw_hours) if str(raw_hours).strip() else 0.0
        
        
        name_val = row.get("Tutor Name", "NA")
        school_val = row.get("Tutor School", "NA")
        email_val = row.get("Email", "NA")
        phone_val = row.get("Phone", "NA")

        tutor = Tutor(
            name=str(name_val).strip() if name_val else "NA",
            school=str(school_val).strip() if school_val else "NA",
            grad=row.get("Grad Year", "NA"), 
            email=str(email_val).strip().lower() if email_val else "NA", 
            phone=str(phone_val).strip() if phone_val else "NA",
            lesson_count=lesson_count,
            submission_count=submission_count,
            total_hours=total_hours,
            last_processed_timestamp=row.get("Last Processed Timestamp", None)
        )
        tutors.append(tutor)
    return tutors

# extract all representatives from reps google sheet
def load_representatives():
    df = fetch_csv(REPRESENTATIVE_CSV_URL)

    if df.empty:
        print("Warning: No representative data found!")
        return DEFAULT_REPS

    print("\nRepresentative Info CSV Columns:", df.columns.tolist())

    column_map = {"name": None, "school": None, "email": None, "phone": None}
    for col in df.columns:
        col_lower = col.lower()
        if "name" in col_lower or "representative" in col_lower:
            column_map["name"] = col
        elif any(term in col_lower for term in ["school", "college", "institution"]):
            column_map["school"] = col
        elif "email" in col_lower or "mail" in col_lower:
            column_map["email"] = col
        elif any(term in col_lower for term in ["phone", "tel", "number", "mobile"]):
            column_map["phone"] = col

    if not all([column_map["name"], column_map["school"], column_map["email"]]):
        print(f"Missing required columns: {column_map}")
        return DEFAULT_REPS

    reps = []
    for _, row in df.iterrows():
        reps.append(Representative(
            name=row.get(column_map["name"], "NA"),
            school=row.get(column_map["school"], "NA"),
            email=row.get(column_map["email"], "NA"),
            phone=row.get(column_map["phone"], "NA") if column_map["phone"] else "NA"
        ))

    present_schools = {rep.school for rep in reps}
    for school in REQUIRED_SCHOOLS - present_schools:
        #print(f"Adding default representative for {school}")
        reps.append(Representative(
            name="Default Rep",
            school=school,
            email=os.getenv("MANAGEMENT_EMAIL", "management@example.com"),
            phone="N/A"
        ))

    return reps

# methods
def attach_lesson_reports_to_tutors(tutors, response_csv_url):
    df = fetch_csv(response_csv_url)
    
    name_col = None
    possible_name_columns = [
        "Select your name from the list.",
        "Name",
        "Tutor Name", 
        "Your Name",
        "Select your name",
        "Tutor",
        "Who are you?"
    ]
    
    for col in possible_name_columns:
        if col in df.columns:
            name_col = col
            break
    
    if not name_col:
        for col in df.columns:
            if "name" in col.lower():
                name_col = col
                break
    
    if not name_col:
        print(f"Name column not found in response sheet. Available columns: {df.columns.tolist()}")
        return

    print(f"Using name column: '{name_col}'")
    
    for tutor in tutors:
        tutor.get_responses(df, name_col)


def save_tutors_to_google_sheet(tutors, sheet_url):
    try:
        print(f"\n=== Attempting to save to Google Sheet ===")
        print(f"Sheet URL: {sheet_url}")
        
        client = get_gspread_client()
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.get_worksheet(0)

        headers = [
            "Tutor Name", "Tutor School", "Grad Year", "Email", "Phone",
            "Total Lessons", "Tutee Name", "Total Hours", "Total Submissions",
            "Latest Weekly Hours", "Taught This Week", "Submitted This Week", "Last Processed Timestamp"
        ]

        data = [[
            t.name, t.school, t.grad, t.email, t.phone,
            t.lesson_count, "", 
            t.total_hours, t.submission_count,
            t.weekly_updates.get("weekly_hours", ""),
            t.weekly_updates.get("taught_lessons", ""),
            t.weekly_updates.get("submitted_this_week", "no"),
            '' if pd.isna(t.last_processed_timestamp) else t.last_processed_timestamp.strftime('%Y-%m-%d %H:%M:%S') 
        ] for t in tutors]

        print(f"Preparing to write {len(data)} tutor records")
        worksheet.clear()
        worksheet.append_rows([headers] + data)
        print("Google Sheet successfully updated.")
        
    except Exception as e:
        print(f"Error saving to Google Sheet: {str(e)}")
        raise

def generate_school_summaries(tutors):
    """Group tutors by school and generate summaries for each school."""
    school_groups = {}
    for tutor in tutors:
        school = tutor.school
        if school not in school_groups:
            school_groups[school] = []
        school_groups[school].append(tutor)

    school_summaries = {}
    for school, tutor_list in school_groups.items():
        summary = generate_summary_for_school(school, tutor_list)
        school_summaries[school] = summary

    return school_summaries

def generate_summary_for_school(school, tutors_in_school):
    summary_lines = []

    for tutor in tutors_in_school:
        ai_summary_text = tutor.summarize_responses() 
        
        if not ai_summary_text or ai_summary_text == "No responses to summarize":
            # For tutors with no responses create a simple status message
            if tutor.weekly_updates.get("submitted_this_week") == "yes":
                line = f"{tutor.name}: Submitted report but did not teach this week."
            else:
                line = f"{tutor.name}: No report submitted this week."
        else:
            # For tutors with AI summaries use just the AI-generated content
            line = f"{tutor.name}: {ai_summary_text}"

        summary_lines.append(line)

    return summary_lines  


if __name__ == "__main__":
    tutors = load_tutors()
    attach_lesson_reports_to_tutors(tutors, RESPONSE_CSV_URL)
    save_tutors_to_google_sheet(tutors, TUTOR_INFO_CSV_URL.replace("/export?format=csv", ""))

    school_summaries = generate_school_summaries(tutors)

    print("\n==== Weekly Tutor Summaries by School ====\n")
    for school, summary in school_summaries.items():
        print(f"===== {school} =====\n{summary}\n")
