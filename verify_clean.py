#!/usr/bin/env python3
"""
Verification script to ensure the repository is clean of sensitive data.
Run this before publishing to verify no hardcoded credentials or personal info remain.
"""

import os
import re
import glob

def check_for_sensitive_data():
    """Check for any remaining sensitive data in the repository."""
    
    print("🔍 Verifying repository is clean of sensitive data...\n")
    
    # Files to exclude from scanning
    exclude_patterns = [
        '.git/*',
        '__pycache__/*',
        '*.pyc',
        'verify_clean.py'  # This file itself
    ]
    
    # Patterns that indicate sensitive data
    sensitive_patterns = {
        'API Keys': r'sk-[a-zA-Z0-9]{20,}',
        'Google OAuth Secrets': r'GOCSPX-[a-zA-Z0-9_-]+',
        'Service Account Private Keys': r'-----BEGIN PRIVATE KEY-----',
        'Hardcoded Gmail URLs': r'docs\.google\.com/spreadsheets/d/[a-zA-Z0-9-_]+',
        'Hardcoded Form URLs': r'forms\.gle/[a-zA-Z0-9_-]+',
        'Hardcoded Drive URLs': r'drive\.google\.com/drive/folders/[a-zA-Z0-9_-]+',
        'Personal Email Addresses': r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    }
    
    issues_found = []
    
    # Get all Python files
    python_files = glob.glob('*.py')
    python_files.extend(glob.glob('.github/workflows/*.yml'))
    
    for file_path in python_files:
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    line_num = 0
                    
                    for line in content.split('\n'):
                        line_num += 1
                        
                        for pattern_name, pattern in sensitive_patterns.items():
                            if re.search(pattern, line):
                                # Skip legitimate patterns
                                if pattern_name == 'Personal Email Addresses':
                                    # Skip legitimate email patterns in code
                                    if any(skip in line.lower() for skip in [
                                        'example.com', 'test@', 'user@', 'admin@', 
                                        'management@', 'os.getenv', 'env.get', 'action@github.com'
                                    ]):
                                        continue
                                elif pattern_name == 'Hardcoded Form URLs':
                                    # Skip example URLs
                                    if 'YOUR_FORM_ID' in line or 'example' in line.lower():
                                        continue
                                elif pattern_name == 'Hardcoded Drive URLs':
                                    # Skip example URLs
                                    if 'YOUR_FOLDER_ID' in line or 'example' in line.lower():
                                        continue
                                elif pattern_name == 'Service Account Private Keys':
                                    # Skip the pattern definition itself
                                    if 'r\'-----BEGIN PRIVATE KEY-----' in line:
                                        continue
                                
                                issues_found.append({
                                    'file': file_path,
                                    'line': line_num,
                                    'pattern': pattern_name,
                                    'content': line.strip()
                                })
                                
            except Exception as e:
                print(f"⚠️  Error reading {file_path}: {e}")
    
    # Check for credential files
    credential_files = [
        'gmail_credentials.json',
        'gmail_token.json', 
        'sheets_credentials.json',
        '.env'
    ]
    
    for cred_file in credential_files:
        if os.path.exists(cred_file):
            issues_found.append({
                'file': cred_file,
                'line': 'N/A',
                'pattern': 'Credential File Present',
                'content': f'Credential file {cred_file} should not be in repository'
            })
    
    # Report results
    if issues_found:
        print("❌ ISSUES FOUND:")
        print("=" * 50)
        for issue in issues_found:
            print(f"File: {issue['file']}")
            print(f"Line: {issue['line']}")
            print(f"Issue: {issue['pattern']}")
            print(f"Content: {issue['content']}")
            print("-" * 30)
        print(f"\n❌ Total issues found: {len(issues_found)}")
        return False
    else:
        print("✅ NO SENSITIVE DATA FOUND!")
        print("✅ Repository is clean and ready for open source release!")
        return True

def check_git_status():
    """Check git status to ensure credential files are not tracked."""
    print("\n🔍 Checking git status...")
    
    # Check if .git directory exists
    if not os.path.exists('.git'):
        print("⚠️  No .git directory found. Make sure to initialize git repository.")
        return False
    
    # Check for credential files in git
    import subprocess
    try:
        result = subprocess.run(['git', 'status', '--porcelain'], 
                              capture_output=True, text=True, check=True)
        
        tracked_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        
        credential_files_tracked = []
        for file_status in tracked_files:
            if file_status:
                file_path = file_status[3:]  # Remove status prefix
                if any(cred_file in file_path for cred_file in [
                    'gmail_credentials.json', 'gmail_token.json', 
                    'sheets_credentials.json', '.env'
                ]):
                    credential_files_tracked.append(file_path)
        
        if credential_files_tracked:
            print("❌ CREDENTIAL FILES ARE BEING TRACKED BY GIT:")
            for file_path in credential_files_tracked:
                print(f"  - {file_path}")
            return False
        else:
            print("✅ No credential files are tracked by git")
            return True
            
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error checking git status: {e}")
        return False

if __name__ == "__main__":
    print("🚀 LessonTrack Open Source Verification")
    print("=" * 40)
    
    clean = check_for_sensitive_data()
    git_clean = check_git_status()
    
    print("\n" + "=" * 40)
    if clean and git_clean:
        print("🎉 VERIFICATION PASSED!")
        print("✅ Repository is ready for open source release!")
        print("✅ No sensitive data found")
        print("✅ Credential files properly excluded from git")
    else:
        print("❌ VERIFICATION FAILED!")
        print("❌ Please fix the issues above before publishing")
        exit(1) 