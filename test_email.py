"""Manual delivery check; excluded from automated test collection."""

__test__ = False

if __name__ == "__main__":
    import argparse
    from Email import test_email_system

    parser = argparse.ArgumentParser(description="Send one real test email only with --send.")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--recipient", required=True)
    args = parser.parse_args()
    if not args.send:
        parser.exit(message="No email sent. Pass --send to perform a real delivery check.\n")
    test_email_system(args.recipient)
