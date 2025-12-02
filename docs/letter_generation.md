# Letter Generation Workflow

The lead workspace now embeds the previously separate MailTemplate sender flow so
you can generate solicitation letters directly from a contact card.

## Overview

- Each `BusinessLead` stores `property_raw_hash`, allowing us to resolve the full
  `PropertyView` row (holder name, type, report year, etc.) on demand without
  duplicating fields on the lead.
- Contacts capture structured mailing information (street, city, state, ZIP)
  and a `contact_type`.
- From the lead edit page, every contact card displays a **Generate Letter**
  button. The action is enabled only when the lead is tied to a property and the
  contact has an address.
- The backend selects the correct letter template based on the lead metadata:

  | Lead Owner Type | Business Status                     | Template Key          |
  |-----------------|-------------------------------------|-----------------------|
  | `individual`    | *(n/a)*                             | `individual.html`     |
  | `business`      | `active` (default)                  | `active_business.html`|
  | `business`      | `acquired_or_merged` / `active_renamed` | `acquired_merged.html` |
  | `business`      | `dissolved`                         | `dissolved_no_owner.html` |

- The backend streams the PDF bytes back to the browser so the user’s machine
  downloads the file directly into its default Downloads folder (no new tabs or
  extra prompts). The UI still refreshes the Print Log panel using the JSON
  endpoints, and each entry shows the friendly `Downloads/<filename>.pdf`
  location for reference.

## Dependencies

- We reuse the Playwright → Chromium rendering logic from `MailTemplate`.
- Ensure Playwright is installed and the Chromium browser is available:

  ```bash
  pip install playwright
  playwright install chromium
  ```

- Letter templates live in `templates/letters/` and reference the shared image
  assets from `MailTemplate/img/` (logo, QR code, signature).

## Data Requirements

- Leads should be created from a property record so `property_raw_hash` is set.
- Contacts must include street, city, state, **and ZIP** before the Generate
  Letter action is enabled. The button stays disabled (and explains why) until
  those fields exist.
- For business owners marked as `acquired_or_merged` or `active_renamed`, the
  "New Owner" field on the lead is required; it is automatically surfaced in the
  letter body and subject.

## Customisation

Sender identity (name, title, phone, email, etc.) is defined in
`letters.py` under the context construction block. Update those constants if the
letterhead needs to change.

