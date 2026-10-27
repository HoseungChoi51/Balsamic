"""N4: MEENT's test-design tool and fixed-design evaluations (their code is ``tools.py``)."""
PACKAGE = __package__

CONTRIBUTION = {"tools": {"agent_tools": [f"{PACKAGE}.tools:register_agent_tools"], "operations": [f"{PACKAGE}.tools:register_operations"]}}
