
# LessonTrack Setup Guide

This guide will help you set up LessonTrack for your organization. Follow these steps carefully to ensure all sensitive information is properly configured.

## Prerequisites

- Python 3.7 or higher  
- Google Cloud Platform account  
- OpenAI API account  
- Google Workspace account (for Gmail API)

---

## Step 1: Clone and Install Dependencies

```bash
git clone <your-repo-url>
cd LessonTrackDeploymentCopy-main
pip install -r requirements.txt
```

---

## Step 2: Set Up Environment Variables

1. Copy the example environment file:
   ```bash
   cp env.example .env
   ```

2. Edit the `.env` file with your configuration:
   ```bash
   # OpenAI API Configuration
   OPENAI_API_KEY=your_openai_api_key_here

   # Google Sheets URLs (replace with your actual sheet URLs)
   TUTOR_INFO_CSV_URL=https://docs.google.com/spreadsheets/d/YOUR_TUTOR_INFO_SHEET_ID/export?format=csv
   RESPONSE_CSV_URL=https://docs.google.com/spreadsheets/d/YOUR_FORM_RESPONSES_SHEET_ID/export?format=csv
   REPRESENTATIVE_CSV_URL=https://docs.google.com/spreadsheets/d/YOUR_REPRESENTATIVES_SHEET_ID/export?format=csv&gid=0

   # Google Form and Drive URLs
   FORM_SUBMISSION_URL=https://forms.gle/YOUR_FORM_ID
   DRIVE_FOLDER_URL=https://drive.google.com/drive/folders/YOUR_FOLDER_ID?usp=sharing

   # Email Configuration
   MANAGEMENT_EMAIL=management@yourcompany.com
   SYSTEM_NAME=LessonTrack
   COMPANY_NAME=Your Company Name
   ```

---

## Step 3: Google Cloud Platform Setup

### 3.1 Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)  
2. Create a new project or select an existing one  
3. Enable billing for the project

---

### 3.2 Enable Required APIs

Enable these APIs in your Google Cloud project:
- Gmail API
- Google Drive API
- Google Sheets API

---

### 3.3 Create Gmail API Credentials

1. Go to "APIs & Services" > "Credentials"  
2. Click "Create Credentials" > "OAuth 2.0 Client IDs"  
3. Choose "Desktop application"  
4. Download the JSON file and save it as `gmail_credentials.json` in the project root

---

### 3.4 Create Google Sheets Service Account

1. Go to "APIs & Services" > "Credentials"  
2. Click "Create Credentials" > "Service Account"  
3. Fill in the service account details  
4. Create a new key (JSON format)  
5. Download and save as `sheets_credentials.json` in the project root

---

### 3.5 Set Up Service Account Credentials Securely

To ensure each organization uses their own credentials and keeps sensitive data secure, follow these steps:

#### 3.5.1 Create a Service Account File

After following [Step 3.4](#34-create-google-sheets-service-account), you’ll receive a `.json` file with credentials. To integrate it safely:

- **Do not commit this file to GitHub**
- Rename the file to:
  ```
  sheets_credentials.json
  ```
- Move it to the project root

#### 3.5.2 Use the Credential Template

This project includes a template you can copy to safely onboard your own credentials:

```
sheets_credentials_template.json
```

Example:
```json
{
  "type": "service_account",
  "project_id": "YOUR_PROJECT_ID",
  "private_key_id": "YOUR_PRIVATE_KEY_ID",
  "private_key": "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY\n-----END PRIVATE KEY-----\n",
  "client_email": "YOUR_CLIENT_EMAIL",
  "client_id": "YOUR_CLIENT_ID",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "YOUR_CLIENT_CERT_URL",
  "universe_domain": "googleapis.com"
}
```

To set it up:
```bash
cp sheets_credentials_template.json sheets_credentials.json
```

Then fill in your actual values from the downloaded service account JSON.

---

## Step 4: Google Sheets Setup

### 4.1 Create Required Google Sheets

You need three Google Sheets:

1. **Tutor Information Sheet** – Master list of tutors and their data  
2. **Form Responses Sheet** – Linked to your Google Form  
3. **Representatives Sheet** – List of school representatives

---

### 4.2 Share Sheets with Service Account

1. Get the service account email from `sheets_credentials.json` (look for `client_email`)  
2. Share each Google Sheet with this email address  
3. Grant "Editor" access to the service account

---

### 4.3 Set Up Sheet Structure

#### Tutor Information Sheet Columns:
- `Tutor Name`  
- `Tutor School`  
- `Grad Year`  
- `Email`  
- `Phone`  
- `Total Lessons` (initially 0)  
- `Total Submissions` (initially 0)  
- `Total Hours` (initially 0.0)  
- `Last Processed Timestamp` (initially blank)

#### Form Responses Sheet:
- Must be linked to your Google Form  
- Should have a column for tutor name selection  
- Must have a `Timestamp` column

#### Representatives Sheet:
- `Name`  
- `School`  
- `Email`  
- `Phone`

---

## Step 5: Google Form Setup

1. Create a Google Form for weekly tutor reports  
2. Link it to the Form Responses Sheet  
3. Include questions for:
   - Tutor name selection  
   - Whether they taught this week  
   - Number of hours taught  
   - Any additional notes

---

## Step 6: OpenAI API Setup

1. Go to [OpenAI Platform](https://platform.openai.com/)  
2. Create an account and get an API key  
3. Add the API key to your `.env` file

---

## Step 7: Test the Setup

### 7.1 Test Email System
```bash
python test_email.py
```

### 7.2 Test Sunday Logic (without sending emails)
```bash
python test_sunday_no_email.py
```

### 7.3 Test Monday Reminders
```bash
python Monday.py
```

### 7.4 Test Full Sunday Process
```bash
python Sunday.py
```

---

## Step 8: Automation Setup

### For Local Development:
- Set up cron jobs or Windows Task Scheduler  
- Run `Monday.py` every Monday  
- Run `Sunday.py` every Sunday

### For Production:
- Consider using GitHub Actions, AWS Lambda, or similar cloud services  
- Set up proper logging and monitoring  
- Implement error handling and notifications

---

## Security Best Practices

1. **Never commit credential files to Git**
   - The `.gitignore` file is already configured to exclude them  
   - Always use environment variables for sensitive data

2. **Rotate credentials regularly**
   - Update API keys periodically  
   - Monitor for unusual activity

3. **Limit API permissions**
   - Only grant necessary permissions to service accounts  
   - Use principle of least privilege

4. **Monitor costs**
   - Set up billing alerts for OpenAI API usage  
   - Monitor Google Cloud API usage

---

## Troubleshooting

### Common Issues:

1. **"Missing required environment variables"**  
   - Check that your `.env` file exists and has all required variables  
   - Ensure no spaces around the `=` sign in `.env` file

2. **"Gmail authentication failed"**  
   - Ensure `gmail_credentials.json` exists and is valid  
   - Run the script locally first to generate `gmail_token.json`

3. **"Google Sheets permission denied"**  
   - Verify the service account email has access to all sheets  
   - Check that sheet URLs are correct and accessible

4. **"OpenAI API error"**  
   - Verify your API key is correct and has sufficient credits  
   - Check OpenAI service status

---

## Support

For additional help or questions, please refer to the main `README.md` file or create an issue in the repository.

---
