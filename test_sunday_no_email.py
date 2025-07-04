from ai_summary import (
    load_tutors,
    attach_lesson_reports_to_tutors,
    save_tutors_to_google_sheet,
    generate_school_summaries,
    RESPONSE_CSV_URL,
    TUTOR_INFO_CSV_URL
)

def test_sunday_no_email():
    print("\\n=== Starting Test Sunday (No Email) Reporting Process ===")


    tutors = load_tutors()
    if not tutors:
        print("No tutors found. Aborting test run.")
        return


    print("\\n=== Attaching Lesson Reports ===")
    attach_lesson_reports_to_tutors(tutors, RESPONSE_CSV_URL)


    print("\\n=== Saving Updated Tutor Data to Google Sheet ===")
    save_tutors_to_google_sheet(tutors, TUTOR_INFO_CSV_URL.replace("/export?format=csv", ""))


    print("\\n=== Generating School Summaries ===")
    school_summaries = generate_school_summaries(tutors)


    print("\\n=== Weekly Tutor Summaries by School (Console Output) ===\\n")
    if school_summaries:
        for school, summary in school_summaries.items():
            print(f"===== {school} =====")
            print(summary)
            print("\\n------------------------------------\\n")
    else:
        print("No school summaries were generated.")

    print("=== Finished Test Sunday (No Email) Reporting Process ===")

if __name__ == "__main__":
    print("Running Test Sunday (No Email) script...")
    test_sunday_no_email()
    print("Test Sunday (No Email) script completed.") 