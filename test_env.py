from dotenv import load_dotenv
import os

load_dotenv()

required_vars = [
    "TUTOR_INFO_CSV_URL",
    "RESPONSE_CSV_URL",
    "REPRESENTATIVE_CSV_URL",
    "OPENAI_API_KEY"
]

for var in required_vars:
    value = os.getenv(var)
    print(f"{var}: {value}")

if all(os.getenv(var) for var in required_vars):
    print("All required environment variables are loaded!")
else:
    print("Some required environment variables are missing.") 