"""A method that ends on its own: a one-shot heuristic, an exhausted enumeration, a search that converged.

A method finishes by returning no proposal (an optimizer_v1 module's ``propose`` returns ``[]`` or raises
``StopIteration``; an ask/tell optimizer's ``ask`` raises ``StopIteration``). Its wrapper raises ``MethodFinished`` and
the worker records the run as completed with reason ``method_finished``, its best kept, rather than as a failure.
"""


class MethodFinished(Exception):
    """The method has nothing more to propose; ``reason`` is its own account of why, when it gives one."""

    def __init__(self, reason=None):
        super().__init__(reason or "The method finished")
        self.reason = reason
