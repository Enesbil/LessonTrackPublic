from Email import send_weekly_reports

def Sunday():
    print("Starting Sunday reporting process...")
    send_weekly_reports()
    print("Finished Sunday reporting process.")

print("Running Sunday script...")
Sunday()
print("Sunday script completed.")
