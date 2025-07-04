#Email.py
import base64
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from email.mime.text import MIMEText
from dotenv import load_dotenv
from ai_summary import (
    load_tutors, 
    load_representatives, 
    generate_school_summaries,
    attach_lesson_reports_to_tutors,
    RESPONSE_CSV_URL,
    TUTOR_INFO_CSV_URL,
    save_tutors_to_google_sheet
)

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

# Management team emails 
MANAGEMENT_EMAILS = [
    os.getenv("MANAGEMENT_EMAIL", "management@yourcompany.com"), 
]

FORM_SUBMISSION_URL = os.getenv("FORM_SUBMISSION_URL", "https://forms.gle/YOUR_FORM_ID")
DRIVE_FOLDER_URL = os.getenv("DRIVE_FOLDER_URL", "https://drive.google.com/drive/folders/YOUR_FOLDER_ID?usp=sharing")
SYSTEM_NAME = os.getenv("SYSTEM_NAME", "LessonTrack")
COMPANY_NAME = os.getenv("COMPANY_NAME", "Your Company Name")

def send_email(recipient, subject, body, is_failure_notification=False):
    """Sends an email using Gmail API."""
    creds = None
    

    if os.path.exists("gmail_token.json"):
        creds = Credentials.from_authorized_user_file("gmail_token.json", SCOPES)
    

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                print("Refreshing expired Gmail token...")
                creds.refresh(Request())
                

                
                with open("gmail_token.json", "w") as token:
                    token.write(creds.to_json())
                print("Gmail token refreshed successfully.")
            except Exception as e:
                print(f"Failed to refresh Gmail token: {e}")


                if os.environ.get('GITHUB_ACTIONS'):
                    print("ERROR: Running on GitHub Actions - cannot re-authenticate interactively.")
                    raise Exception("Gmail authentication failed - requires manual re-authentication")
                else:
                    print("Attempting to re-authenticate locally...")
                    flow = InstalledAppFlow.from_client_secrets_file("gmail_credentials.json", SCOPES)
                    creds = flow.run_local_server(port=0)
              
                    with open("gmail_token.json", "w") as token:
                        token.write(creds.to_json())
                    print("Successfully re-authenticated and saved new token.")
        else:
            
            if os.environ.get('GITHUB_ACTIONS'):
                print("ERROR: Running on GitHub Actions - no valid Gmail credentials found.")
                print("Please ensure you have valid credentials in your repository.")
                raise Exception("Gmail authentication failed - no valid credentials")
            else:
                print("No valid Gmail credentials found. Attempting to authenticate...")
                flow = InstalledAppFlow.from_client_secrets_file("gmail_credentials.json", SCOPES)
                creds = flow.run_local_server(port=0)
                
                with open("gmail_token.json", "w") as token:
                    token.write(creds.to_json())
                print("Successfully authenticated and saved new token.")
    
    # Build Gmail service
    service = build("gmail", "v1", credentials=creds)
    
    # Create and send email
    message = MIMEText(body)
    message["to"] = recipient
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    
    try:
        send_message = service.users().messages().send(
            userId="me",
            body={"raw": raw}
        ).execute()
        
        print(f"Email sent to {recipient}")
    
    except Exception as e:
        print(f"Failed to send email to {recipient}. Error: {e}")
        
        if not is_failure_notification:
            admin_email = MANAGEMENT_EMAILS[0] if MANAGEMENT_EMAILS else "admin@example.com"
            notification_subject = f"ALERT: Email Delivery Failure to {recipient}"
            notification_body = (
                f"The system failed to send an email.\n"
                f"Recipient: {recipient}\n"
                f"Original Subject: {subject}\n"
                f"Error: {str(e)}"
            )
            print(f"Attempting to send failure notification to {admin_email} regarding the failure to email {recipient}.")
            
            send_email(
                admin_email,
                notification_subject,
                notification_body,
                is_failure_notification=True 
            )

def test_email_system(test_email=None):
    """Send a test email to verify the email system is working."""
    if test_email is None:
        test_email = MANAGEMENT_EMAILS[0] if MANAGEMENT_EMAILS else "test@example.com"
    
    print(f"\n=== Testing Email System with {test_email} ===")
    
    test_body = (
        "Hello,\n\n"
        f"This is a test email from the {SYSTEM_NAME} reporting system.\n\n"
        "If you're receiving this email, the email sending functionality is working correctly.\n\n"
        "Best regards,\n"
        f"{COMPANY_NAME} Automated System"
    )
    
    send_email(
        test_email,
        f"{SYSTEM_NAME}: Email System Test",
        test_body
    )
    
    print(f"Test email sent to {test_email}. Please check your inbox.")

def send_weekly_reports():
    """Send weekly reports to representatives and management."""
    print("\n=== Preparing Weekly Reports ===")
    
    # Load tutors and their latest responses
    tutors = load_tutors()
    if not tutors:
        print("No tutors found. Aborting weekly reports.")
        return
        
    attach_lesson_reports_to_tutors(tutors, RESPONSE_CSV_URL)
    
    save_tutors_to_google_sheet(tutors, TUTOR_INFO_CSV_URL.replace("/export?format=csv", ""))
    

    school_summaries = generate_school_summaries(tutors)
    
    representatives = load_representatives()
    
    # Send school-specific reports to representatives
    print("\n=== Sending Reports to Representatives ===")
    for rep in representatives:
        if rep.school in school_summaries:
            summary = school_summaries[rep.school]
            body = (
                f"Dear {rep.name},\n\n"
                f"Here is this week's summary for {rep.school} tutors:\n\n"
                f"{summary}\n\n"
                "Best regards,\n"
                f"{COMPANY_NAME} Team"
            )
            send_email(
                rep.email,
                f"{SYSTEM_NAME} Weekly Report - {rep.school}",
                body
            )
    
    # Send complete summary to management team
    print("\n=== Sending Complete Report to Management Team ===")
    management_body = "Weekly Tutor Report Summary\n\n"
    
    total_tutors = len(tutors)
    tutors_submitted_this_week = sum(1 for t in tutors if t.weekly_updates.get("submitted_this_week", "no") == "yes")
    tutors_taught_this_week = sum(1 for t in tutors if t.weekly_updates.get("taught_lessons", "no") == "yes")
    total_hours_this_week = sum(t.weekly_hours for t in tutors if isinstance(t.weekly_hours, (int, float)))
    total_hours_all_time = sum(t.total_hours for t in tutors if isinstance(t.total_hours, (int, float)))
    
    management_body += "Overall Statistics:\n"
    management_body += f"Total Tutors: {total_tutors}\n"
    management_body += f"Total Submissions This Week: {tutors_submitted_this_week}\n"
    management_body += f"Total Tutors Who Taught This Week: {tutors_taught_this_week}\n"
    management_body += f"Total Hours This Week: {total_hours_this_week}\n"
    management_body += f"Total Hours All Time: {total_hours_all_time}\n\n"
    
    for school, summary in school_summaries.items():
        management_body += f"\n=== {school} ===\n{summary}\n"
    
    for email in MANAGEMENT_EMAILS:
        send_email(
            email,
            f"{SYSTEM_NAME} Complete Weekly Report - All Schools",
            management_body
        )

def Monday_email_to_tutors():
    tutors = load_tutors() 
    
    if not tutors:
        print("No tutors found to send emails to.")
        return
        
    for tutor in tutors:
 
        if tutor.email == "NA" or "@" not in tutor.email:
            continue

        first_name = tutor.name.strip().split()[0] if tutor.name.strip() else "Tutor"
        message = (
            f"Dear {first_name},\n\n"
            "Here is the Google Forms link to submit your lesson report for this week:\n"
            f"👉 {FORM_SUBMISSION_URL}\n\n"
            "I know its the same link from last week. Don't worry, it still works. Please submit it before Sunday 22:00 GMT, even if you did not have class this week.\n\n"
            "This form helps us ensure every student has an active tutor and is receiving the support needed.\n\n"
            "Thank you so much for your time and dedication!\n\n"
            f"If you have any useful resources you'd like to share with other tutors, please upload them here: {DRIVE_FOLDER_URL}\n\n"
            "If you have any questions, please reach out to your UWC representative or contact me at:\n"
            f"{MANAGEMENT_EMAILS[0]}\n\n"
            "Best regards,\n"
            f"{COMPANY_NAME} Team\n"
            "P.S. This is an automated email, but you can reply to it if you have any questions."
        )
        send_email(
            tutor.email,
            "Important: Please Submit Your Weekly Report",
            message
        )  
  
