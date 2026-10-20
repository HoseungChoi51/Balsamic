"""The problem-definition gate: proposals, allocations, interventions and autopilot wait until the problem is fully defined.

The check is `evolution.stages.definition`. Here it is applied: the service-layer handlers that start work are wrapped for
every actor, a guard refuses the lead's and autopilot's work-starting commands, and the lead's campaign_inspect carries the
gate's state so it can say what is missing instead of starting."""
from balsamic.evolution.stages import definition

GATED = ("research.generate", "hypothesis.allocate", "intervention.batch")
AGENT_GATED = {*GATED, "hypothesis.create", "study.race.create", "trial.create", "draft.launch"}


def check(workspace, campaign_id, what):
    """Raises ValueError naming the missing step when the campaign's problem definition is not complete."""
    campaign = workspace.store.get(campaign_id, "campaign")
    state = definition(workspace, campaign)
    if state["ready"]:
        return state
    step = state["step"]
    raise ValueError(f"{what} waits for the problem definition: {step['title'].lower()} ({step['page']}). {step['text']}")


def register(workspace):
    commands = workspace.commands
    for operation in GATED:
        handler = commands.handlers.get(operation)
        if handler is None:
            continue

        def gated(command, actor, _handler=handler, _operation=operation):
            check(workspace, command.campaign_id, _operation)
            return _handler(command, actor)
        commands.handlers[operation] = gated

    def guard(command, actor, campaign):
        if command.operation in AGENT_GATED:
            check(workspace, campaign["id"], command.operation)
    commands.guards.append(guard)
    workspace.definition_gate = lambda campaign: definition(workspace, campaign)
