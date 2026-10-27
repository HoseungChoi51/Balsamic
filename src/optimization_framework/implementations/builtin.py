"""Auditable binding of an installed method to an existing proposal: by the researcher or an agent, or by Balsamic's system
actor after an install delivered the method (B4)."""
from typing import Any

from pydantic import Field

from optimization_framework.contracts.base import Contract, content_hash
from optimization_framework.contracts.problems import ProblemInstance
from optimization_framework.optimizers.registry import capability_reason, validate_parameters
from optimization_framework.storage.sqlite import now


class BuiltinBindingInput(Contract):
    hypothesis_id: str
    task_id: str
    algorithm: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    expected_algorithm: str
    expected_configuration_hash: str
    reason: str = Field(min_length=1, max_length=10000)
    # The library install Balsamic binds after; required of its system actor.
    install_id: str | None = None


def bind(workspace, campaign_id, payload, command_id, *, actor='researcher'):
    values = BuiltinBindingInput.model_validate(payload)
    hypothesis = workspace.store.get(values.hypothesis_id, 'hypothesis')
    task = workspace.store.get(values.task_id, 'task')
    if hypothesis['campaign_id'] != campaign_id or task['campaign_id'] != campaign_id:
        raise ValueError('The proposal and validation task must belong to this campaign')
    if actor == 'balsamic':
        _check_install(workspace, campaign_id, hypothesis, values)
    if hypothesis.get('implementation_version_id'):
        raise ValueError('This proposal already has a published executable binding')
    if (hypothesis['algorithm'] != values.expected_algorithm or
            content_hash(hypothesis.get('algorithm_config', {})) != values.expected_configuration_hash):
        raise ValueError('Proposal implementation changed; refresh the binding')
    instance = ProblemInstance(**task['problem'])
    from optimization_framework.agents.library_validation import refused_reason
    reason = refused_reason(workspace.store, values.algorithm) or capability_reason(values.algorithm, instance)
    if reason:
        raise ValueError(reason)
    validate_parameters(values.algorithm, instance, values.parameters)
    record = {'id': 'builtin_binding_' + command_id, 'campaign_id': campaign_id, 'hypothesis_id': hypothesis['id'],
        'task_id': task['id'], 'algorithm': values.algorithm, 'parameters': values.parameters,
        'previous_algorithm': hypothesis['algorithm'], 'previous_parameters': hypothesis.get('algorithm_config', {}),
        'reason': values.reason, 'created_at': now(), 'validation_level': 'bundled_regression', 'authority': actor,
        **({'install_id': values.install_id} if values.install_id else {})}
    workspace.store.put_immutable('builtin_binding', record, 'implementation.builtin_bound')
    # The configuration the first binding replaced is what a concept review judged (proposals.hypothesis_revision).
    hypothesis.setdefault('pre_binding_config', hypothesis.get('algorithm_config', {}))
    hypothesis.update(algorithm=values.algorithm, algorithm_config=values.parameters,
                      builtin_binding_id=record['id'], executable=True, implementation_status='builtin')
    workspace.store.put('hypothesis', hypothesis, 'hypothesis.implementation_bound')
    return {'binding_id': record['id'], 'hypothesis_id': hypothesis['id'], 'algorithm': values.algorithm}


def _check_install(workspace, campaign_id, hypothesis, values):
    """Balsamic binds only what an install it cites delivered: a proposal the submission serves, to a method its report names
    for it, and never a proposal someone already bound."""
    from optimization_framework.campaigns.method_catalog import methods_for, served
    if not values.install_id:
        raise ValueError("Balsamic's binding cites the library install it follows")
    install = workspace.store.get(values.install_id, 'library_install')
    if install['campaign_id'] != campaign_id or install['status'] != 'installed':
        raise ValueError('The cited install is not a completed install of this campaign')
    submission = workspace.store.get(install['submission_id'], 'development_submission')
    if hypothesis['id'] not in served(submission) or values.algorithm not in methods_for(submission, hypothesis['id']):
        raise ValueError(f"The cited install does not deliver {values.algorithm} for {hypothesis['id']}")
    if hypothesis.get('builtin_binding_id'):
        raise ValueError('The proposal is already bound; Balsamic does not bind it again')
