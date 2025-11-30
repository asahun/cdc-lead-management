# Property Detail Modal

## Purpose

The properties list now supports an in-place detail view that surfaces the full
record from `PropertyView` without leaving the table. Users can inspect all
columns, move to adjacent properties, close the modal to return to the list, or
immediately create a lead from the detail pane.

## Behavior

- Trigger via the compact “details” pill button or by clicking directly on a table row. Next/Prev now request the next record from the API even if it isn’t loaded in the table, following the same property-amount ordering as the table (ties broken by the row hash so duplicates stay stable).
- The properties list remembers your most recent page/search using `localStorage`, so navigating away and back resumes where you left off.
- Fetches `/properties/{property_id}` which returns `property_detail.html`.
- The modal loads the fragment dynamically, showing:
  - Property basics (ID, owner, amount)
  - Any additional columns exposed on the model (looped generically)
  - Navigation buttons (Prev/Next) styled as ghost pills
  - A primary add-to-lead pill button plus a floating close control (hidden when the property is already linked to a lead)
- Properties already assigned to a lead render a green **Linked to Lead** badge and swap the footer call-to-action with a reminder to jump back into the existing lead workspace.
- Modal can be dismissed with the close icon or by clicking outside.

## Implementation Notes

- `main.py` now exposes `GET /properties/{property_id}` and guards the new-from-property flow so already-linked records redirect straight to their lead. Navigation helpers rebuild the row ordering on demand with window functions (no stored `order_id` column required).
- `PropertyView` now maps to the backing table (`ucp_main_year_e_2025`) instead of the read-only view, leaning on `row_hash` as the stable primary key and projecting an `assigned_to_lead` flag for UI state.
- Frontend pieces:
- `templates/properties.html` keeps the table layout compact while embedding the `<dialog>` container and script hook.
- `templates/property_detail.html` renders the detail card.
- `static/js/property_detail.js` wires up modal interactions, paging, and fetch (calling `/api/properties/{property_id}` for Next/Prev).
- `static/js/properties_state.js` persists the last visited page/search via `localStorage` so returning users land where they left off.
- `static/css/styles.css` adds modern table hover states, pill buttons, and a gradient modal shell with card-style fields.
- Table rows expose both their property ID and `raw_hash` in `data-*` attributes; the modal prioritizes `raw_hash` for navigation so duplicate IDs/amounts don't break sequencing.
- The same modal is reused inside the lead workspace; `/properties/by_hash/{raw_hash}` serves the fragment without navigation/add-to-lead actions when requested with `context=lead`.

## Follow-up Ideas

- Remember the last viewed property across sessions for quicker modal re-open.
- Support keyboard shortcuts for closing or paging (Esc, ←, →).
- Show richer formatting (currency, address formatting, links) once data set is finalized.

