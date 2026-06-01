#!/usr/bin/env python3
"""Read job application emails from the last week and save to Google Sheets."""

import os
import base64
import json
import re
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

CLIENT_SECRET = os.path.expanduser(
    "~/Downloads/client_secret_582768099331-d68qj2hosr6715m4fn48hqi2auj7n1ud.apps.googleusercontent.com.json"
)
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "google_token.json")
SHEET_ID = "1moobWnElaLyn7qcTq7H3q5oPeErH81xJRul40buGtuk"
SHEET_RANGE = "Sheet1!A:C"

STATUS_KEYWORDS = {
    "Rejected": [
        "unfortunately", "not moving forward", "decided to move forward with other",
        "not selected", "position has been filled", "we will not", "not a match",
        "regret to inform", "other candidates", "not the right fit",
    ],
    "Interview Scheduled": [
        "interview", "technical interview", "onsite", "virtual interview",
        "zoom interview", "google meet", "teams interview", "panel interview",
    ],
    "Call Scheduled": [
        "phone screen", "phone call", "intro call", "recruiter call",
        "screening call", "discovery call", "chat scheduled",
    ],
    "Applied": [
        "received your application", "application received", "application submitted",
        "thank you for applying", "thanks for applying", "we have received",
        "your application for", "successfully applied",
    ],
}


def classify_status(subject: str, body: str) -> str:
    text = (subject + " " + body).lower()
    for status, keywords in STATUS_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return status
    return "Applied"


def extract_job_info(subject: str, body: str, sender: str) -> dict:
    """Extract job title and company from email content."""
    # Try to extract company from sender domain
    company = ""
    match = re.search(r"@([\w.-]+)\.", sender)
    if match:
        domain = match.group(1)
        # Skip generic email providers
        if domain not in ("gmail", "yahoo", "hotmail", "outlook", "icloud", "lever", "greenhouse", "workday", "ashbyhq", "myworkdayjobs"):
            company = domain.replace("-", " ").replace(".", " ").title()

    # Try to extract from email body patterns
    body_lower = body.lower()

    # Pattern: "position of X at Y" or "role of X at Y"
    for pattern in [
        r"(?:position|role|opportunity) (?:of |for )?[\"']?(.+?)[\"']? at ([A-Z][\w\s&,.-]+?)(?:\.|,|\n)",
        r"(?:applied|application) (?:for )?(?:the )?[\"']?(.+?)[\"']? (?:position|role|job) at ([A-Z][\w\s&,.-]+?)(?:\.|,|\n)",
        r"(?:applied|application) (?:for )?(?:the )?([A-Z][\w\s]+?) (?:position|role) at ([A-Z][\w\s&,.-]+?)(?:\.|,|\n)",
    ]:
        m = re.search(pattern, body, re.IGNORECASE)
        if m:
            return {"title": m.group(1).strip(), "company": m.group(2).strip()}

    # Fall back to parsing subject line
    # Common subject patterns: "Your application for X at Y", "Application - X | Y"
    for pattern in [
        r"(?:application|applied) (?:for )?(?:the )?[\"']?(.+?)[\"']? at (.+?)(?:\s*[-|]|$)",
        r"(.+?) at (.+?) - (?:application|applied)",
        r"(.+?)\s*[-|]\s*(.+?)\s*[-|]",
    ]:
        m = re.search(pattern, subject, re.IGNORECASE)
        if m:
            title = m.group(1).strip(" '\"")
            comp = m.group(2).strip(" '\"")
            if len(title) < 80 and len(comp) < 80:
                return {"title": title, "company": comp or company}

    # Last resort: use subject as title
    title = re.sub(r"^(re:|fw:|fwd:)\s*", "", subject, flags=re.IGNORECASE).strip()
    return {"title": title, "company": company}


def get_email_body(payload) -> str:
    """Recursively extract plain text body from email payload."""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    for part in payload.get("parts", []):
        text = get_email_body(part)
        if text:
            return text
    return ""


def is_job_related(subject: str, body: str) -> bool:
    job_keywords = [
        "application", "applied", "position", "role", "interview", "recruiter",
        "hiring", "job", "candidate", "offer", "opportunity", "thank you for applying",
        "your application", "phone screen", "onsite", "technical screen",
    ]
    text = (subject + " " + body[:500]).lower()
    return any(kw in text for kw in job_keywords)


def main():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    gmail = build("gmail", "v1", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)

    # Search emails from the last 7 days
    cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y/%m/%d")
    query = f"after:{cutoff} to:lukeren314@gmail.com OR from:lukeren314@gmail.com"
    print(f"Searching emails since {cutoff}...")

    results = gmail.users().messages().list(
        userId="me", q=query, maxResults=100
    ).execute()
    messages = results.get("messages", [])
    print(f"Found {len(messages)} emails in the last week")

    job_apps = []
    seen = set()

    for msg in messages:
        detail = gmail.users().messages().get(
            userId="me", id=msg["id"], format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in detail["payload"]["headers"]}
        subject = headers.get("Subject", "")
        sender = headers.get("From", "")
        body = get_email_body(detail["payload"])

        if not is_job_related(subject, body):
            continue

        info = extract_job_info(subject, body, sender)
        status = classify_status(subject, body)
        key = (info["title"].lower(), info["company"].lower())
        if key in seen:
            continue
        seen.add(key)

        job_apps.append([info["title"], info["company"], status])
        print(f"  [{status}] {info['title']} @ {info['company']}")

    if not job_apps:
        print("No job application emails found.")
        return

    # Read existing sheet data to avoid duplicates
    existing = sheets.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=SHEET_RANGE
    ).execute().get("values", [])

    existing_keys = set()
    start_row = 1
    if existing:
        # Check if first row is a header
        if existing[0] and existing[0][0].lower() in ("job title", "title", "position"):
            data_rows = existing[1:]
            start_row = 2
        else:
            data_rows = existing
        for row in data_rows:
            if len(row) >= 2:
                existing_keys.add((row[0].lower(), row[1].lower()))

    new_rows = [r for r in job_apps if (r[0].lower(), r[1].lower()) not in existing_keys]

    if not new_rows:
        print("All found applications are already in the sheet.")
        return

    # Write header if sheet is empty
    if not existing:
        header = [["Job Title", "Company", "Status"]]
        sheets.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body={"values": header},
        ).execute()
        append_range = "Sheet1!A2"
    else:
        append_range = SHEET_RANGE

    sheets.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range=append_range,
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": new_rows},
    ).execute()

    print(f"\nAdded {len(new_rows)} new job applications to the sheet.")


if __name__ == "__main__":
    main()
