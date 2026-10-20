# Panels: pages the agents compose

Decided 2026-10-20. A panel is a declarative page fragment the lead or the formulator composes from a catalog of
Balsamic components. No code travels from an agent to the browser: the panel is JSON validated against
`balsamic/panels/schema.py`, every component is rendered by the workspace's own React components, values are resolved
from the records on the server at read time, fields write through the charter service with a receipt, and buttons issue
bus commands as the researcher. The hand-built pages stay for problem-independent mechanics; panels carry what a
particular problem needs and no fixed page has.

## Catalog

| Component | What it shows or does | Data |
|---|---|---|
| `markdown` | text with math, record ids and page links | inline `text` |
| `kv` | labelled values | `rows[{label, value}]`, or `bind` to a charter quantity (`{charter, value: name}`), or `record {id, field}` |
| `table` | records of one kind | `source {kind, fields, where, limit}` over `TABLE_KINDS` (hypothesis, trial, decision, study, adaptive_race, asset, thread, task; public fields only), or inline `rows` |
| `number` | a number field | `bind {charter, path}` with `quantities.<name>.value|expression` or `variables.<index>.lower|upper`; `min`, `max`, `units` |
| `select` | one of some options | `bind {charter, question}` (answers the formulator's question) or a charter path; `options[{value, label}]` |
| `chart` | a score curve | `source {trial}` or `{hypothesis}` (its best run), or inline `points` |
| `button` | a bus command the researcher issues | `command {operation, payload}`; agent control and campaign creation are not a button's |
| `link` | a page | `page` (#address) |
| `section` | a titled group | `children` |

Limits: 64 KiB, 60 components, one page per panel (`page` is a rail address or a sub page), `placement` top or bottom.
Component ids are unique within a panel; fields and buttons need one.

## Service and API

`balsamic/panels/service.py`: `validate` (schema, then every binding against the campaign's charter and records, every
button against the declared operations), `create` (a record of kind `panel`, revision counted; a panel made in a
conversation thread posts one `panel_link` line there, shown as a card with the panel inline), `resolve` (the panel with
`data[component_id]` filled: bound values with their units and charter revision, table rows, curve points), `set_value`
(a number or select → `charters.edit` or `charters.answer`, with the component's bounds checked), `for_page`, `retire`.

Routes: `GET /api/v1/campaigns/{id}/panels?page=#note/charter` (a page shows its own panels and those of its sub pages),
`GET /api/v1/panels/{id}`, `POST /api/v1/panels/{id}/set {component_id, value}`, `POST /api/v1/panels/{id}/retire`.
SSE kinds `panel.created|revised|retired` refetch the panels and the chat.

Tools: the lead's `panel_render {title, page, components, placement?, note?, panel_id?}` (any page; a panel from a
conversation is announced there); the formulator's `panel_render {title, components, …}` (the charter page of the
campaign that adopted its charter, reached through `workspace.panels`, the hook the service installs so the core never
imports the service layer).

Frontend: `panels/PanelView.tsx` renders a resolved panel; `panels/PanelsOnPage.tsx` puts a page's panels above or below
its fixed content (`shell/StagePanel.tsx`); `chat/Turn.tsx` shows a `panel_link` message as a card. Number fields share
`NumberField` with the charter form, so a value shows "saved" or its refusal beside the field.

## Roadmap and to-do

- **Done 2026-10-20.** Catalog of nine components, server-side resolution, charter-bound fields, bus-bound buttons,
  panels on pages and in the chat, the lead's and the formulator's tools, tests (`tests/balsamic/test_panels.py`,
  `frontend/tests/panels.spec.ts`).
- **Next.** Express the fixed charter form's quantities and variables as a generated panel (proof that the catalog
  carries the form); a `records` binding for `kv` on more kinds; a `form` component that groups fields with one Apply.
- **To do: decide on A2UI adoption. Review by 2027-01-20** (three months after this decision, 2026-10-20). The panel
  shape follows A2UI's component-tree idea so that its renderer could replace `PanelView` later. Decide after the first
  real campaigns used panels: compare the catalog we needed against A2UI's, check its renderer's maturity (tables, charts,
  theming) and whether its event model can carry the bus's receipts. Owner: the researcher; the telemetry gate
  (`GET /api/v1/ui-events/gate`) and the panel records (`author`, `revision`, components used) are the evidence.
- **Later.** Marimo notebooks for analysis ("Open in notebook" from a campaign, trial or race; the lead authors analysis
  notebooks through the implementation validation path, run in the sandbox).
