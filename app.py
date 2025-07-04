from flask import Flask, render_template, jsonify
import os
from dotenv import load_dotenv
from ai_summary import (
    load_tutors,    
    load_representatives, 
    generate_school_summaries,
    attach_lesson_reports_to_tutors,
    save_tutors_to_google_sheet
)

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')

# --- Live Data Route ---
@app.route('/')
def index():
    try:
        TUTOR_INFO_CSV_URL = os.getenv("TUTOR_INFO_CSV_URL")
        RESPONSE_CSV_URL = os.getenv("RESPONSE_CSV_URL")

        if not TUTOR_INFO_CSV_URL or not RESPONSE_CSV_URL:
            raise ValueError("TUTOR_INFO_CSV_URL and RESPONSE_CSV_URL must be set in your .env file.")

        # Load current tutor data from Google Sheet 
        tutors = load_tutors()
        if not tutors:
            return render_template('error.html', message="Could not load tutor data. Please check your TUTOR_INFO_CSV_URL in the .env file and ensure the sheet is shared correctly.")

        # Load representatives for display
        representatives = load_representatives()

        total_tutors = len(tutors)
        active_this_week = sum(1 for t in tutors if t.weekly_updates.get("taught_lessons") == "yes")
        submitted_this_week = sum(1 for t in tutors if t.weekly_updates.get("submitted_this_week") == "yes")
        total_hours_this_week = sum(t.weekly_hours for t in tutors if isinstance(t.weekly_hours, (int, float)))
        total_hours_all_time = sum(t.total_hours for t in tutors if isinstance(t.total_hours, (int, float)))

        stats = {
            'total_tutors': total_tutors,
            'active_this_week': active_this_week,
            'submitted_this_week': submitted_this_week,
            'total_hours_this_week': round(total_hours_this_week, 1),
            'total_hours_all_time': round(total_hours_all_time, 1)
        }
        
        # Group tutors by school for the view
        tutors_by_school = {}
        for tutor in tutors:
            school = tutor.school
            if school not in tutors_by_school:
                tutors_by_school[school] = []
            tutors_by_school[school].append(tutor)

        # Create empty summaries for display 
        school_summaries = {}
        for school in tutors_by_school.keys():
            school_summaries[school] = ["Click 'Refresh Data' to generate AI summaries"]

        return render_template('dashboard.html',
                             tutors=tutors,
                             representatives=representatives,
                             summaries=school_summaries,
                             tutors_by_school=tutors_by_school,
                             stats=stats,
                             live_data=True) 
                             
    except Exception as e:
        error_message = f"An error occurred: {e}. Please ensure your .env file and API credentials (sheets_credentials.json) are set up correctly."
        print(error_message)
        return render_template('error.html', message=error_message)

# --- Manual Refresh Route ---
@app.route('/refresh')
def refresh_data():
    try:
        TUTOR_INFO_CSV_URL = os.getenv("TUTOR_INFO_CSV_URL")
        RESPONSE_CSV_URL = os.getenv("RESPONSE_CSV_URL")

        if not TUTOR_INFO_CSV_URL or not RESPONSE_CSV_URL:
            raise ValueError("TUTOR_INFO_CSV_URL and RESPONSE_CSV_URL must be set in your .env file.")

        tutors = load_tutors()
        if not tutors:
            return render_template('error.html', message="Could not load tutor data. Please check your TUTOR_INFO_CSV_URL in the .env file and ensure the sheet is shared correctly.")


        attach_lesson_reports_to_tutors(tutors, RESPONSE_CSV_URL)

    
        save_sheet_url = TUTOR_INFO_CSV_URL.replace("/export?format=csv", "")
        save_tutors_to_google_sheet(tutors, save_sheet_url)
        school_summaries = generate_school_summaries(tutors)
        representatives = load_representatives()

        total_tutors = len(tutors)
        active_this_week = sum(1 for t in tutors if t.weekly_updates.get("taught_lessons") == "yes")
        submitted_this_week = sum(1 for t in tutors if t.weekly_updates.get("submitted_this_week") == "yes")
        total_hours_this_week = sum(t.weekly_hours for t in tutors if isinstance(t.weekly_hours, (int, float)))
        total_hours_all_time = sum(t.total_hours for t in tutors if isinstance(t.total_hours, (int, float)))

        stats = {
            'total_tutors': total_tutors,
            'active_this_week': active_this_week,
            'submitted_this_week': submitted_this_week,
            'total_hours_this_week': round(total_hours_this_week, 1),
            'total_hours_all_time': round(total_hours_all_time, 1)
        }
        

        tutors_by_school = {}
        for tutor in tutors:
            school = tutor.school
            if school not in tutors_by_school:
                tutors_by_school[school] = []
            tutors_by_school[school].append(tutor)

        return render_template('dashboard.html',
                             tutors=tutors,
                             representatives=representatives,
                             summaries=school_summaries,
                             tutors_by_school=tutors_by_school,
                             stats=stats,
                             live_data=True) 
                             
    except Exception as e:
        error_message = f"An error occurred: {e}. Please ensure your .env file and API credentials (sheets_credentials.json) are set up correctly."
        print(error_message) 
        return render_template('error.html', message=error_message)

# --- Tutor Profile Route ---
@app.route('/tutor/<tutor_name>')
def tutor_profile(tutor_name):
    try:
        TUTOR_INFO_CSV_URL = os.getenv("TUTOR_INFO_CSV_URL")
        RESPONSE_CSV_URL = os.getenv("RESPONSE_CSV_URL")

        if not TUTOR_INFO_CSV_URL or not RESPONSE_CSV_URL:
            raise ValueError("TUTOR_INFO_CSV_URL and RESPONSE_CSV_URL must be set in your .env file.")

        # Load all tutors to find the specific one
        tutors = load_tutors()
        if not tutors:
            return render_template('error.html', message="Could not load tutor data.")

        # Find the specific tutor
        tutor = None
        for t in tutors:
            if t.name.lower() == tutor_name.lower():
                tutor = t
                break
        
        if not tutor:
            return render_template('error.html', message=f"Tutor '{tutor_name}' not found.")

        ai_summary = tutor.summarize_responses()

        return render_template('tutor_profile.html',
                             tutor=tutor,
                             ai_summary=ai_summary,
                             live_data=True)
                             
    except Exception as e:
        error_message = f"An error occurred: {e}. Please ensure your .env file and API credentials (sheets_credentials.json) are set up correctly."
        print(error_message)
        return render_template('error.html', message=error_message)

# Test Data (Demo Page)
MOCK_TUTORS = [
    {
        "name": "Aisha Khan",
        "school": "UF",
        "email": "aisha.k@email.com",
        "total_lessons": 45,
        "total_submissions": 12,
        "total_hours": 67.5,
        "weekly_hours": 5.5,
        "taught_this_week": "Yes",
        "submitted_this_week": "Yes",
        "last_submission": "2024-01-15 14:30:00"
    },
    {
        "name": "Javier Garcia",
        "school": "Mostar",
        "email": "javier.g@email.com",
        "total_lessons": 38,
        "total_submissions": 10,
        "total_hours": 52.0,
        "weekly_hours": 4.0,
        "taught_this_week": "Yes",
        "submitted_this_week": "Yes",
        "last_submission": "2024-01-15 16:45:00"
    },
    {
        "name": "Chloe Nguyen",
        "school": "RBC",
        "email": "chloe.n@email.com",
        "total_lessons": 52,
        "total_submissions": 15,
        "total_hours": 78.0,
        "weekly_hours": 6.0,
        "taught_this_week": "Yes",
        "submitted_this_week": "Yes",
        "last_submission": "2024-01-15 13:15:00"
    },
    {
        "name": "Omar Al-Farsi",
        "school": "UF",
        "email": "omar.af@email.com",
        "total_lessons": 29,
        "total_submissions": 8,
        "total_hours": 43.5,
        "weekly_hours": 0.0,
        "taught_this_week": "No",
        "submitted_this_week": "Yes",
        "last_submission": "2024-01-15 17:20:00"
    },
    {
        "name": "Fatima Bello",
        "school": "Mostar",
        "email": "fatima.b@email.com",
        "total_lessons": 41,
        "total_submissions": 11,
        "total_hours": 61.5,
        "weekly_hours": 4.5,
        "taught_this_week": "Yes",
        "submitted_this_week": "Yes",
        "last_submission": "2024-01-15 15:10:00"
    }
]

MOCK_REPRESENTATIVES = [
    {"name": "Dr. Evelyn Reed", "school": "UF", "email": "evelyn.reed@uf.edu"},
    {"name": "Mr. Kenji Tanaka", "school": "Mostar", "email": "kenji.tanaka@mostar.edu"},
    {"name": "Dr. Sofia Rossi", "school": "RBC", "email": "sofia.rossi@rbc.edu"}
]

MOCK_SUMMARIES = {
    "UF": [
        "Aisha Khan: Taught 5.5 hours this week focusing on advanced English grammar. Student showed significant improvement in constructing complex sentences. No safety concerns detected.",
        "Omar Al-Farsi: Submitted report but did not teach this week due to student scheduling conflicts. Will resume next week."
    ],
    "Mostar": [
        "Javier Garcia: Conducted 4 hours of ESL conversation practice, covering verb tenses and pronunciation. Student engagement was excellent with role-playing scenarios.",
        "Fatima Bello: Provided 4.5 hours of TOEFL preparation, focusing on reading comprehension strategies and vocabulary building. Student is showing great progress."
    ],
    "RBC": [
        "Chloe Nguyen: Delivered 6 hours of comprehensive English literature tutoring. Covered Shakespeare's Macbeth with detailed character analysis. Student showed exceptional critical thinking skills."
    ]
}

@app.route('/demo')
def dashboard():
    total_tutors = len(MOCK_TUTORS)
    active_this_week = sum(1 for tutor in MOCK_TUTORS if tutor['taught_this_week'] == 'Yes')
    submitted_this_week = sum(1 for tutor in MOCK_TUTORS if tutor['submitted_this_week'] == 'Yes')
    total_hours_this_week = sum(tutor['weekly_hours'] for tutor in MOCK_TUTORS)
    total_hours_all_time = sum(tutor['total_hours'] for tutor in MOCK_TUTORS)
    
    tutors_by_school = {}
    for tutor in MOCK_TUTORS:
        school = tutor['school']
        if school not in tutors_by_school:
            tutors_by_school[school] = []
        tutors_by_school[school].append(tutor)
    
    return render_template('dashboard.html',
                         tutors=MOCK_TUTORS,
                         representatives=MOCK_REPRESENTATIVES,
                         summaries=MOCK_SUMMARIES,
                         tutors_by_school=tutors_by_school,
                         stats={
                             'total_tutors': total_tutors,
                             'active_this_week': active_this_week,
                             'submitted_this_week': submitted_this_week,
                             'total_hours_this_week': total_hours_this_week,
                             'total_hours_all_time': total_hours_all_time
                         },
                         live_data=False)

@app.route('/demo/email-reminder')
def demo_email_reminder():
    return render_template('demo_email.html', 
                         action="Reminder Sent",
                         message="Monday reminder emails sent to all tutors",
                         tutors=MOCK_TUTORS)

@app.route('/demo/weekly-report')
def demo_weekly_report():
    return render_template('demo_email.html',
                         action="Weekly Reports Generated",
                         message="Sunday weekly reports processed and sent to representatives and management",
                         tutors=MOCK_TUTORS)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080) 