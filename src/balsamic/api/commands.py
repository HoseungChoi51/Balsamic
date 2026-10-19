"""The command bus over HTTP: the researcher's boundary. Agents reach the bus through their tools, never this route."""
from optimization_framework.contracts.commands import Command


def install(app, workspace):
    @app.post("/api/v1/commands")
    def work_command(body: Command):
        # HTTP is the local researcher boundary. Internal agent calls use the
        # manager actor explicitly and cannot choose a stronger authority.
        return workspace.commands.execute(body, actor="researcher")

    @app.get("/api/v1/commands/{command_id}")
    def command_outcome(command_id: str):
        return workspace.store.get(command_id, "work_command")

    @app.get("/api/v1/commands/{command_id}/delivery")
    def command_delivery(command_id: str):
        return workspace.commands.delivery(command_id)

    @app.get("/api/v1/command-catalog")
    def command_catalog():
        """Every operation with its payload schema and whether the lead may run it under delegation."""
        return workspace.commands.describe()
