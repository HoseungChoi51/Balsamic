# Partnership protocol: alone, and with Balsamic

| Item | Detail |
|---|---|
| Part | Roadmap J3 (Phase 2). The metrics are `balsamic/monitor/partnership.py` and the Monitor's Partnership tab |
| Who runs it | Hoseung, once per phase, after the phase's release is tagged |
| Question | Does the researcher do better with the agents than alone? System-only operation is an ablation, not the goal |

## The four numbers

For each attempt, record the same four numbers. Balsamic measures them per request; the attempt alone is timed by hand.

| Number | With Balsamic (Monitor → Partnership) | Alone |
|---|---|---|
| Researcher actions | "Your actions": messages, decisions and other commands from the request to the lead's report | Count the prompts written to the coding agent plus the commands and edits made by hand |
| Time | "To report" and "To ranked result" | From starting to the first time the methods are ranked, and to the answer |
| Cost | "Worker time" and "Model $" | Wall time of the runs (as a single worker's seconds) and the coding agent's model dollars |
| Result | "Best by then", in the objective's direction | The best objective reached, in the same direction, on the same evaluator |

## The problem

Use the same small problem every time, so the phases can be compared: the `bounded_continuous` quadratic (minimize), at its
default configuration. Later phases may add a second problem (J2's `deflector_2d` or `reactor` presets), recorded in its own
rows.

## Steps

1. **Alone.** Take the problem as a Python project: the exported project once F2 has landed (the Charter tab's "Export as
   Python project"), until then the problem's own module. Open it in a local coding agent. Ask it to implement and run two
   different methods, compare them at the same cost, and report the best. Start a stopwatch at the first prompt; stop it at
   the answer. Note the prompts and hand edits, the runs' wall time and the agent's model dollars.
2. **With Balsamic.** Start a new campaign on the same problem with the same budget. In the main chat, send one request:
   "Implement and run two different methods, compare them at the same cost, and tell me which is best." Answer what the
   lead asks, and approve what it asks for. When the lead reports, open Monitor → Partnership and copy the request's row.
3. Record both in the table below, with the commit or release tag, the model and the date.

## Results

| Date | Release or commit | Model | Attempt | Actions | To ranked result | To answer | Worker time | Model $ | Best |
|---|---|---|---|---|---|---|---|---|---|

## Reading the results

- Balsamic should need fewer researcher actions and reach a result at least as good. A better best at a much higher cost,
  or more actions, is not a win; say so.
- "To ranked result" is "none" when the lead never ran a comparison report: a finding in itself.
- A request that is still open has no report time; its other numbers are as of now.
- Requests open at the same time each count the researcher's actions in their own window, so actions can be counted twice.
  Send one request at a time when running the protocol.
