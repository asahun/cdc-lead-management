# XSS Findings (Tracking)

This document tracks potential XSS surfaces identified during refactoring reviews.
It is not a remediation plan yet; it is a map of where unescaped HTML can enter
the DOM or templates.

## Summary Buckets

- File-based templates (trusted if repo-controlled): phone scripts, email templates,
  LinkedIn templates.
- User-editable content: email compose body, scheduled email content.
- Externally sourced content: entity intel AI/SOS data.
- Server-rendered output with `|safe`.

## Findings (By Area)

### Templates (server-rendered)

- `templates/lead_form.html:377`
  - Uses `|safe` for `prop.holder_name`.
  - If `holder_name` contains HTML, it will render unescaped.
  - Suggested direction: remove `|safe` and render fallback markup without injecting raw HTML.

### Phone Scripts

- `static/js/leads/phone_scripts.js:106`
  - Injects `script.html` into `innerHTML` after placeholder replacement.
  - Source is `templates/phone/*.html` via `helpers/phone_scripts.py` and `utils/html_processing.py`.
  - These are file-based (not UI-editable), but still allow HTML.
  - Suggested direction: if hardening needed, sanitize with an allowlist or render as text.

### Email Templates + Compose

- `static/js/leads/email_compose/index.js:115`
  - Injects `data.body` from `/leads/.../email-prep` into `innerHTML`.
  - `data.body` is built from `templates/email/*.html` (file-based).
- `static/js/leads/email_compose/index.js` + `static/js/leads/scheduled_emails.js:148`
  - User-edited email body is persisted and re-inserted via `innerHTML`.
  - Suggested direction: sanitize stored email HTML or allowlist tags on render.

### Scheduled Emails List

- `static/js/leads/scheduled_emails.js:84`
  - Builds HTML via template literals containing `email.subject`, `contact_name`,
    `error_message`, etc.
  - These values can be user-entered; should be escaped or rendered via `textContent`.

### LinkedIn Templates

- `static/js/leads/linkedin_templates/index.js:183`, `:192`
  - Injects `data.preview`, `templateName`, and `error.message` into `innerHTML`.
  - Source is `templates/linkedin/templates.json` (file-based).
  - Suggested direction: render preview as text with `white-space: pre-wrap`, or sanitize.

### Entity Intel

- `static/js/leads/entity_intel/render.js:660`, `:687`
  - Builds HTML from AI/SOS response data and injects into `innerHTML`.
  - This is externally sourced and should be escaped or rendered via DOM APIs.

### Journey Display

- `static/js/leads/journey_display/render.js:32`
  - Builds HTML from journey data including contact names/titles.
- `static/js/leads/journey_display/index.js:65`
  - Injects `data.error` into `innerHTML`.
  - Suggested direction: use DOM nodes and `textContent` for user data.

### Lead List Task Indicator

- `static/js/leads/list/task_indicator/render.js:49`
  - Renders task labels/icons via `innerHTML`.
  - Suggested direction: build nodes and set `textContent`.

### Lead Bulk Confirm Modal

- `static/js/leads/list/leads_bulk/render.js:32`
  - Uses `innerHTML` for confirm message (low risk if content is strictly internal).
  - Suggested direction: ensure inputs to message are controlled or escape user-facing parts.

### Property Detail Modal

- `static/js/properties/property_detail/index.js:18`
  - Injects server-rendered HTML into `innerHTML`.
  - Safe only if server templates always escape user data.
