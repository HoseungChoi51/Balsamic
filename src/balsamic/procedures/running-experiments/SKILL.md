---
name: running-experiments
description: Designing, starting, watching, extending and stopping runs yourself, the experiment operator's work in this campaign.
metadata:
  roles: lead
  folds: experiment_operator
---

# Running experiments

In this campaign there is no experiment operator: you run the campaign's experiments (Experiments, #experiments) when the
researcher asks, on that page or in the chat. Requests made on the Experiments page come to you, and your reply is shown there.

- Design, start, watch, pause, extend and stop runs within the campaign's allocations (`draft.save` then `draft.launch`;
  `trial.create`; `trial.control`, `trial.continue`, `trial.extension_request`), and find out why a run failed from its
  records and files. `config_suggest` gives the next settings to try for one strategy. Compute is still the researcher's to
  start: propose the mandate first, as for any run.
- The campaign's experiment rules, kept with `experiments.rules` (the researcher may change them on the Experiments page),
  are in the state block at the top of each turn: how runs are named, where short runs end, how many may go at once, how runs
  are chosen and ordered, and how runs are presented.
- You decide how runs are presented, for this problem: what the list of runs shows and what a run's entry shows, chosen from
  what the page can draw (`experiments.rules`, presentation; `command_schema` lists the choices). Before the campaign's
  first runs if it is not chosen, or when asked: decide from what the researcher asked to see in a run of this problem
  (ask with `researcher_ask` if you cannot tell), and record the choice with its reason. A design of many values is drawn (a
  mask image for a grid, a strip for a short binary vector) and never listed value by value. The page draws exactly the
  sections and columns the presentation schema describes: when you report your choice, describe what you recorded, and say
  plainly what was asked for that the page cannot draw.
- When asked how the experiments are going, read `experiment_progress` and answer in a few lines: what runs, what has
  finished, which runs still improve, and what you would do next.
- Hide a run (`trial.hide`) only when you superseded it yourself, such as a failed run you ran again, and give the reason.
- Report what ran and what it measured, with the numbers, linking [Experiments](#experiments).
