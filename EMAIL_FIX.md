# Email Notification Fix for Production (Render)

## Problem

Render (and many cloud hosting providers) block outbound SMTP connections on ports 587 and 465 for security reasons. This causes the error:

```
OSError: [Errno 101] Network is unreachable
```

## Solution Implemented

Updated `notification_service.py` with:

1. **Dual-port fallback**: Try port 587 (TLS) first, then port 465 (SSL)
2. **Better error handling**: Specific messages for network issues
3. **Timeout configuration**: 10-second timeout to fail fast

## Alternative Solutions for Production

Since Render blocks SMTP ports, you have 3 options:

### Option 1: Use SendGrid (Recommended)

**Why**: Free tier (100 emails/day), Render-friendly, reliable

**Setup**:
1. Sign up at https://sendgrid.com
2. Get API key from Settings → API Keys
3. Install: `pip install sendgrid`
4. Update `.env`:
   ```
   SENDGRID_API_KEY=your_api_key_here
   ```

**Code changes needed**: Minimal - just replace SMTP with SendGrid API

### Option 2: Use Mailgun

**Why**: Free tier (5,000 emails/month), good for transactional emails

**Setup**:
1. Sign up at https://mailgun.com
2. Get API key and domain
3. Install: `pip install requests` (already installed)
4. Use Mailgun API instead of SMTP

### Option 3: Use AWS SES

**Why**: Very cheap ($0.10 per 1,000 emails), highly reliable

**Setup**:
1. Set up AWS account
2. Verify email in SES
3. Install: `pip install boto3`
4. Use SES API

## Quick Fix: Disable Email Notifications

If you want the system to work without emails temporarily:

**In `.env`**, remove or comment out:
```env
# GMAIL_USER=
# GMAIL_APP_PASSWORD=
# NOTIFICATION_RECIPIENT=
```

The system will log a warning but continue working normally, storing companies in CRM without sending emails.

## Recommendation

For production on Render, use **SendGrid** (easiest) or disable email notifications until you can set up a proper email service.

The current code will gracefully handle the failure and continue storing companies in CRM.
