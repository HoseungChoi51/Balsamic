---
name: report-brief
description: Starting the report writer, and what to do while it works (report_write).
metadata:
  roles: lead
---

# Report brief

When the researcher asks for a report, start the report writer with `report_write`. Its `notes` say what the report is about
and what to leave out; `reference_ids` name the records it starts from. The writer sees the campaign's runs, hypotheses,
decisions, sources and studies by itself; what agents wrote (reviewers' verdicts and saved analyses, `agent_artifact`;
assistants' replies, `agent_run`) it sees only when listed in `reference_ids`.

1. Say that the report is being written and that its progress shows on [Reports](#reports).
2. Call `yield_work(waiting)`: the writer takes many minutes, and its end wakes you.
3. If the writer asks about the focus, answer with `report_answer` when the request settles it; otherwise pass the question
   to the researcher.
4. When it ends, give the link to the draft in a line or two.

Do not write the report in the chat. One report is written at a time.
