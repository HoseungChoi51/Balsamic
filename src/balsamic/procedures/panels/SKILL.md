---
name: panels
description: Composing a panel when a page lacks an input or a view (panel_render).
metadata:
  roles: lead
---

# Panels

When a fixed page lacks an input or a view this problem needs (a table of seats to fill, a few charter quantities to set
together, a curve beside a decision), compose one with `panel_render` from the catalog instead of asking for values in chat.

- The researcher types into it; values go through the charter with a receipt.
- The panel appears on its page and as a card in this conversation.
- Revise it with its `panel_id` rather than making another.
