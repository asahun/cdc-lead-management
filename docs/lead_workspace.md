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
  on the lead’s owner type/status and saves the PDF into `lead_app/print/`.
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

## Follow-up Ideas

- Use htmx or fetch API to submit contact/attempt forms asynchronously.
- Add quick filters or sorting within the attempts list.
- Surface attempt counts or last-touch timestamps in the lead list view.

