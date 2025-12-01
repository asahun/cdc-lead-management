# Email Configuration Guide

## Environment Variables Required

Set these environment variables before running the application:

### SMTP Configuration (IONIO)

```bash
# SMTP Server (default: smtp.ionos.com)
SMTP_HOST=smtp.ionos.com

# SMTP Port (default: 587)
SMTP_PORT=587

# SMTP Username (your IONIO email account)
SMTP_USERNAME=info@loadrouter.com

# SMTP Password (your IONIO email password)
SMTP_PASSWORD=your_password_here

# From Email Address (what recipients see)
SMTP_FROM_EMAIL=fisseha@loadrouter.com

# From Name (display name)
SMTP_FROM_NAME=Fisseha Gebresilasie

# Reply-To Address (optional, defaults to SMTP_FROM_EMAIL)
SMTP_REPLY_TO=fisseha@loadrouter.com
```

## Setting Environment Variables

### Windows (PowerShell)
```powershell
$env:SMTP_HOST="smtp.ionos.com"
$env:SMTP_PORT="587"
$env:SMTP_USERNAME="info@loadrouter.com"
$env:SMTP_PASSWORD="your_password_here"
$env:SMTP_FROM_EMAIL="fisseha@loadrouter.com"
$env:SMTP_FROM_NAME="Fisseha Gebresilasie"
$env:SMTP_REPLY_TO="fisseha@loadrouter.com"
```

### Windows (Permanent - Environment Variables)
1. Open "Environment Variables" in Windows Settings
2. Add the variables under "User variables" or "System variables"
3. Restart your terminal/application

### macOS/Linux
```bash
export SMTP_HOST="smtp.ionos.com"
export SMTP_PORT="587"
export SMTP_USERNAME="info@loadrouter.com"
export SMTP_PASSWORD="your_password_here"
export SMTP_FROM_EMAIL="fisseha@loadrouter.com"
export SMTP_FROM_NAME="Fisseha Gebresilasie"
export SMTP_REPLY_TO="fisseha@loadrouter.com"
```

## Code Defaults (Temporary Values)

If you prefer to set temporary values in code, edit `email_service.py`:

```python
# Lines 20-26 in email_service.py
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.ionos.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "info@loadrouter.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "your_temp_password")  # ⚠️ Change this
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "fisseha@loadrouter.com")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Fisseha Gebresilasie")
SMTP_REPLY_TO = os.getenv("SMTP_REPLY_TO", "fisseha@loadrouter.com")
```

**⚠️ Warning:** Hardcoding passwords in code is not recommended for production. Use environment variables instead.

## Testing Email Configuration

1. Start the application
2. Navigate to a lead with a contact that has an email address
3. Click "Prep Email" on the contact card
4. Review the pre-filled subject and body
5. Click "Send" to test the email delivery

## Troubleshooting

### "SMTP_PASSWORD environment variable is not set"
- Ensure `SMTP_PASSWORD` is set in your environment or in the code defaults

### "Failed to send email: Authentication failed"
- Verify your `SMTP_USERNAME` and `SMTP_PASSWORD` are correct
- Check that your IONIO account allows SMTP access

### "Connection timeout"
- Verify `SMTP_HOST` and `SMTP_PORT` are correct
- Check firewall settings
- Ensure TLS/SSL is enabled (port 587 uses STARTTLS)

## Email Template Mapping

The system automatically selects email templates based on lead status:

- **dissolved** → `dissolved_inactive.html`
- **acquired_or_merged** → `acquired_merged.html`
- **active_renamed** → `acquired_merged.html` (uses acquired template)
- **active** → `active_company.html`
- **individual** → `Individual.html`
- **No match** → Empty body (user composes manually)

## Placeholder Substitution

Templates use placeholders that are automatically replaced:

- `[FirstName]` → First word of contact name
- `[ID]` → Property ID
- `[Company Legal Name]` → Owner name (for active)
- `[Old Entity Legal Name]` → Owner name (for acquired)
- `[OldBusinessName]` → Owner name (for dissolved)
- `[New Entity Name]` → New business name (if available)
- `[YYYY]` → Report year from property
- `[HolderName]` / `[Holder Name]` → Holder name from property
- `[Type]` → Property type description
- `[Amount]` / `[Exact or Range]` → Formatted property amount

