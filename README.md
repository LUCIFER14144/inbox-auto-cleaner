<<<<<<< HEAD
# Inbox Auto-Cleaner

A FastAPI application that searches email accounts and can automatically delete emails after a specified period.

## Features

- Search emails across multiple email accounts (Gmail, Yahoo, Outlook)
- Search by sender email or subject line
- Auto-delete emails older than specified minutes
- Admin panel for managing auto-delete functionality
- Dry-run mode for safety
- Detailed deletion logging

## Setup

1. Configure email accounts in `EMAIL_CONFIG` environment variable as JSON:

```json
{
  "accounts": [
    {
      "email": "your-email@gmail.com",
      "password": "app-specific-password",
      "name": "Your Name"
    }
  ]
}
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Usage

- **Search**: Go to `/` to search emails
- **Admin**: Go to `/admin` to manage auto-delete

## Security Notes

- Never commit `config.json` to repository
- Use app-specific passwords for Gmail/Yahoo/Outlook
- Always test in dry-run mode first
- Keep deletion logs for audit trail
- Deleted emails cannot be recovered
=======
# inbox-auto-cleaner
FastAPI application for searching emails and auto-deleting old emails from multiple email accounts
>>>>>>> e8b7562641c1da2ffdf13a7efe50a435597e24cc
