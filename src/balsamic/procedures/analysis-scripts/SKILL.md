---
name: analysis-scripts
description: Reading repository and experiment files; analysing journals with a sandboxed script (analysis_run).
metadata:
  roles: lead, discussion_moderator, experiment_operator, implementation_lead, resource_planner, literature_specialist, methodology_specialist, cross_domain_explorer, skeptical_domain_analyst, empirical_assessor, proposal_reviewer, results_analyst
---

# Analysis scripts

`file_list`, `file_read` and `file_search` read this server's repository (its committed source, tests and documents) and the
files of this campaign's experiments (root `experiment` with a `trial_id`). Read the code or the documents before concluding how
something works.

To analyse journals or results beyond what a record shows:

1. Write a Python script with `workspace_write`.
2. Run it with `analysis_run`, naming the experiments: they are mounted read-only at `/data/<trial_id>`. numpy and
   `optimization_framework.execution.metrics` (`scalar_rows`, `full_row`, `recent_metrics`) can be imported; there is no network
   and no GPU.
3. Print a short result: whatever a tool returns stays in your context.
