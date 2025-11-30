# Lead Management App

FastAPI application for managing business leads and unclaimed property records.

## Prerequisites

- Python 3.10 or higher
- PostgreSQL database
- OpenAI API key (for entity intelligence features)

## Installation (Windows)

### 1. Install Python

```powershell
# Using winget (recommended)
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements

# Close and reopen PowerShell, then verify:
python --version
```

### 2. Clone or copy the project

```powershell
cd C:\path\to\your\projects
git clone <repository-url> lead_app
# OR copy the project folder manually
```

### 3. Create and activate a virtual environment (recommended)

```powershell
cd lead_app
python -m venv .venv
.\.venv\Scripts\activate
```

**Note:** Virtual environments are recommended but not required. They isolate dependencies from other Python projects.

### 4. Install dependencies

```powershell
pip install -r requirements.txt
```

### 5. Install Playwright browser (for PDF generation)

```powershell
playwright install chromium
```

### 6. Set environment variables

In PowerShell, set these before running the app:

```powershell
# Database connection (adjust as needed)
$env:DATABASE_URL="postgresql+psycopg2://username:password@localhost:5432/database_name"

# OpenAI API key (required for entity intelligence)
$env:OPENAI_API_KEY="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"

# Optional: Custom GPT model
$env:GPT_ENTITY_MODEL="gpt-5.1"

# Optional: Request timeout
$env:GPT_ENTITY_TIMEOUT_SECONDS="45"
```

**To make environment variables permanent:**
- Open "Environment Variables" in Windows Settings
- Add them under "User variables" or "System variables"

### 7. Run the server

```powershell
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The app will be available at `http://localhost:8000`

## Project Structure

- `main.py` - FastAPI application and routes
- `models.py` - SQLAlchemy database models
- `db.py` - Database connection configuration
- `gpt_api.py` - OpenAI integration for entity intelligence
- `letters.py` - PDF letter generation
- `templates/` - Jinja2 HTML templates
- `static/` - CSS, JavaScript, and image assets

## Features

- Lead management with contacts, attempts, and comments
- Property detail views with assignment tracking
- Entity intelligence via GPT (successor research)
- PDF letter generation for contacts
- Responsive UI with localStorage state persistence

