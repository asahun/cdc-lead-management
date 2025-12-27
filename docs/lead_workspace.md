# Lead Workspace

## Purpose

The lead workspace centralizes everything related to a single `BusinessLead`
record. Instead of sending users to separate pages, the lead edit view now
handles:

- Core lead metadata (property details, status, ownership type/size)
- Contact management
- Outreach attempt logging

This keeps high-frequency actions in one place and removes redundant
navigation clicks.

## User Flow

1. Open a lead through `/leads/{id}/edit`.
2. Update the lead summary at the top of the page and click **Save Lead**.
3. Scroll (or jump via `#contacts` / `#attempts`) to manage contacts and
   attempts directly below the summary.
4. When a contact or attempt form is submitted the app redirects back to the
   same section anchor so the user remains in context.

Existing URLs `/leads/{id}/contacts` and `/leads/{id}/attempts` now redirect
to the combined workspace, so old bookmarks continue to work.

## Implementation Notes

- `main.py` loads contacts, attempts (sorted newest-first), and enum choices
  directly in the edit route context.
- The `lead_form.html` template uses shared “card” and “data-table” components,
  includes a dedicated comment log, and now captures structured ownership
  metadata (business vs individual, statuses, new name, size). A compact **View Detail**
  button appears in the header beside the status pill, launching the shared property
  modal (without Prev/Next) so agents can inspect the full property snapshot without
  leaving the lead.
- Properties fetched from the list carry a persisted `assigned_to_lead` flag; once a lead
  is created the property row highlights in green, the “Add to Lead” link is swapped for a
  **Linked** badge, and any attempt to start another lead from that property redirects to
  the existing lead workspace.
- Contact forms capture contact type plus street/city/state/ZIP, which are
  rendered as compact cards in the UI.
- `static/styles.css` includes reusable page/card/table primitives that are
  shared across the lead detail, contacts, attempts, and comments views.
- Leads now persist the `property_raw_hash` from the source property view, which
  allows downstream features (e.g. letter generation) to pull the complete
  property record without duplicating fields on the lead.
- The lead header now includes an **Entity Intelligence** card (above the comment log).
  Clicking **Run Analysis** calls `/leads/{id}/entity-intel`, which wraps
  `fetch_entity_intelligence` in `gpt_api.py` to ask OpenAI for original/successor/claimant
  data and renders the response in place using `static/js/entity_intel.js`. Holder name and
  last activity date already appear in the property record, so the card focuses exclusively
  on successor details and the recommended claimant.
- OpenAI access is configured via environment variables: set `OPENAI_API_KEY` (required) and,
  optionally, `OPENAI_BASE_URL`, `GPT_ENTITY_MODEL`, or `GPT_ENTITY_TIMEOUT_SECONDS`
  to override the defaults.
- Letter generation reuses the MailTemplate PDF workflow: each contact card
  provides a **Generate Letter** action that renders the correct template based
  on the lead’s owner type/status and streams the PDF back to the user so it
  lands in their default Downloads folder, while the backend logs the job so it
  appears in the Print Log panel.
- PDF tooling: pdfrw + reportlab filler (`scripts/pdf_fill_reportlab.py`) plus
  per-template handlers `scripts/fill_recovery_agreement.py` (UP-CDR2) and
  `scripts/fill_recover_authorization_letter.py` (Authorization Letter).
  Templates live in `scripts/pdf_templates/`, outputs in `scripts/pdf_output/`,
  and static CDR data in `scripts/data/cdr_profile.json`. Claim tracking uses
  `scripts/sql/003_add_claim_tables.sql`.
- Claim-first flow (response_received leads):
  - Header CTA sits next to One-Pager: “Create Claim” calls POST `/leads/{id}/claims`
    to snapshot control_no/formation_state/fee_pct/addendum + primary contact/CDR profile
    into `claim` and assigns `scripts/pdf_output/claim-{id}`. Create buttons disable once a claim exists.
  - Lead view always shows **View Claim** when a claim exists (regardless of lead status); if no claim and the lead is `response_received`, a **Create Claim** button appears. Generation lives on the claim page.
  - Claims list: GET `/claims` shows all claims (slug, lead, control #, fee %, last event, doc count).
  - Claim detail: GET `/claims/{id}` shows summary, events, documents (generated vs claim package), and
    “Generate Agreement Files” (POST `/claims/{id}/agreements/generate`).
  - Claim package uploads: POST `/claims/{id}/documents/upload` saves files into the claim output dir and
    logs `claim_document`; package list separates generated outputs from uploaded package artifacts.
  - APIs: GET `/leads/{id}/claims/latest`, `/leads/{id}/agreements/events`, `/leads/{id}/agreements/documents`;
    claim-scoped GET `/claims/{id}/events`, `/claims/{id}/documents`.
- The properties list automatically filters out stale records—only rows with
  `last_seen` greater than or equal to the most recent Monday at 6 PM (Eastern)
  are shown. This lines up with the weekly refresh cadence so the UI never shows
  data older than the latest batch.
- `static/local_time.js` converts ISO timestamps to the viewer’s locale so
  activity history (attempts, comments) is easy to read.
- The global header contains a **Profile** switcher (Fisseha vs Abby). The choice
  is stored in `localStorage`, drives comment authorship, and passes through every
  email action so the correct signature and SMTP sender (e.g. `abby@loadrouter.com`)
  are applied automatically (scheduled emails embed the profile marker so the
  scheduler can send with the right identity).
- Each lead header now includes a subtle delete icon that opens a confirmation modal before permanently deleting the lead (and clearing the property assignment flag).
- A “Phone Scripts” card at the bottom of the lead view surfaces registered-agent, decision-maker, and gatekeeper scripts with placeholders automatically populated from the current profile and lead/property data (plus a copy-to-clipboard action).
- Contact names are normalized before rendering outbound communications: email greetings always use a capitalized first name, while letters print a properly cased full name in the address block and a first-name salutation even when the CRM data arrives in all caps.
- Letter generation streams PDFs to the browser (no new tab), logs each print beneath the attempts list, and lets you mark the letter as mailed—checking the box automatically writes a `mail` attempt for that contact.
- Lead statuses now include `competitor_claimed`, which is used by the weekly
  refresh job to flag properties that have aged out (per the cutoff rule above).
  Add the enum value in Postgres via:

  ```sql
  ALTER TYPE lead_status ADD VALUE IF NOT EXISTS 'competitor_claimed';
  ```

- The `lead_status` enum also retains `claim_created` for compatibility with
  existing rows created during the claim rollout. The UI still surfaces the
  claim presence via the “Has Claim” badge; no behavior change is tied to that
  status value.
- Claim “current status” is derived only from status events (`claim_created`,
  `agreement_generated`, `agreement_sent`, `agreement_signed`, `claim_preparing`,
  `claim_submitted`, `pending`, `approved`, `rejected`, `more_info`), not from
  file-only events like uploads/deletions. Generation events are both statuses
  and file-related, so they appear in filters for both “Status” and “Files”.
- Claim detail now supports PDF preview: a “Preview” button opens a modal with an
  inline iframe; “Open in new tab” is available, and a disabled “Send for
  Signature” button is staged for the next phase. Downloads support `?inline=1`
  via `/claims/{id}/files/download` and `/claims/{id}/documents/{doc_id}/download`.
- PDF generation uses pdfrw+reportlab to draw text directly for consistent
  rendering across viewers. Authorization letter maps `entity_name` (new
  template field) and `business_name` to the lead’s `owner_name`.

  To bulk update older leads during a refresh:

  ```sql
  WITH cutoff AS (
    SELECT date_trunc('week', now()) - interval '7 days' + interval '18 hours' AS ts
  )
  UPDATE business_lead bl
  SET status = 'competitor_claimed',
      updated_at = now()
  FROM properties p, cutoff c
  WHERE bl.property_id = p.property_id
    AND p.last_seen < c.ts
    AND bl.status <> 'competitor_claimed';
  ```

## Follow-up Ideas

- Use htmx or fetch API to submit contact/attempt forms asynchronously.
- Add quick filters or sorting within the attempts list.
- Surface attempt counts or last-touch timestamps in the lead list view.

