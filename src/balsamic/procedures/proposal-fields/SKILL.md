---
name: proposal-fields
description: What each field of a proposal must say, and correcting one (hypothesis.create, hypothesis.edit).
metadata:
  roles: lead, discussion_moderator
---

# Proposal fields

The researcher reads every proposal on [Hypotheses](#hypotheses) as a card: its label (H01…), title, stage and readiness
badges, the search lane, the round, its reviews. Each field you record is a statement, so make every one of them true and
specific.

| Field | What it says |
|---|---|
| `title` | One line naming the strategy and what sets it apart from its siblings (not the family alone) |
| `short_title` | Two or three words for the lineage graph (the housekeeper writes one when you do not) |
| `mechanism` | What is done and how, concretely enough to implement |
| `rationale` | Why it should win on this problem, with the assumption it rests on |
| Formulas | In `mechanism` and `rationale`, write each formula in LaTeX: inline as `$D(S)=\min_{j\in S}\,[D(S\setminus\{j\})+\max(0,P(S)-d_j)]$`, or as a display on a line of its own between `$$`. The card renders them; plain text such as `Σ_{i∈S}p_i` stays raw |
| `algorithm` | The installed search procedure that will run its experiments, chosen on purpose from `campaign_inspect.methods` for the task's representation. Left out, the default (hillclimb) is recorded and the page marks it as not chosen: choose, or state `custom` when nothing installed fits and say so in the mechanism |
| `algorithm_config` | The parameters that lane accepts, named |
| `parent_links` | The parent and the kind (revision, variant, hybrid, inspired_by) when a proposal derives from another |
| `round` | The generation round |

After recording, read the card as the researcher will. Correct a wrong or empty field with `hypothesis.edit` (the lane and its
parameters only before the proposal has run), and never explain a field away in chat instead of fixing it.

The researcher asks for strategies (`research.generate`, or in words); the lead owns that request and records each strategy
with `hypothesis.create`. The discussion moderator reviews recorded proposals in rounds with its specialists and can run a
generation round when asked; it does not start rounds by itself.
