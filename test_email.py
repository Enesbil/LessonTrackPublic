# test_email.py
from Email import test_email_system

if __name__ == "__main__":
    print("=== LessonTrack Email System Test ===")
    # The test_email_system function will use the management email from environment variables
    test_email_system()
    print("Test complete!")