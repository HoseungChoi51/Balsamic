---
name: review-rounds
description: Running a review round over proposals yourself, the discussion moderator's work in this campaign.
metadata:
  roles: lead
  folds: discussion_moderator
---

# Review rounds

In this campaign there is no discussion moderator: you run the review of the campaign's proposals (Hypotheses, #hypotheses)
when the researcher asks, on that page or in the chat. Requests made on the Hypotheses page come to you, and your reply is
shown there.

1. Ask the specialists and the reviewers for their views and verdicts on the proposals named (`delegate`): a
   `proposal_reviewer` per proposal (`hypothesis_id`), and the specialists the question needs (a `skeptical_domain_analyst`
   for failure modes, a `methodology_specialist` for the installed methods that fit, a `literature_specialist` for sources).
   Call `yield_work(waiting)`; their results come back to you.
2. A reviewer's `proposal_review` is the record of its verdict: report each verdict in the reviewer's own word (test, revise
   or reject), and do not record it again with `hypothesis.review`.
3. Have proposals revised where the verdicts ask for it (`hypothesis.edit`, or a new revision), and set each proposal's
   status (`hypothesis.status`). A status that goes against the reviewers' verdicts is recorded with them, not refused: say why.
4. Record the round's synthesis with `review_synthesis` once its reviews are in: each proposal's standing (stands, revise,
   rejected) with the reviews it rests on and why. You cannot end the request (`yield_work(complete)`) after asking
   reviewers until the synthesis is recorded.
5. Reply in a few lines: which proposals stand, which were revised or rejected, and why, linking
   [Hypotheses](#hypotheses).
