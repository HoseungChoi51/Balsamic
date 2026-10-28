"""Host-only plugin, separate from the reusable numeric modules."""
from optimization_framework.optimizers.packaged import PackagedPlugin
from importlib import import_module
subset_dp, due_date_insertion, swap_search = [import_module(__package__ + '.' + name) for name in
                                               ('subset_dp', 'due_date_insertion', 'swap_search')]


class Plugin(PackagedPlugin):
    REPRESENTATIONS = ['permutation']
    METHODS = {
        'subset_dp_exact_scheduling': {
            'module': subset_dp, 'name': 'Subset DP', 'description': 'Elapsed-time total tardiness subset DP.',
            'hypothesis_id': 'hypothesis_pi_command_476837ad6603990c15d2240c6558dca2'},
        'due_date_insertion': {
            'module': due_date_insertion, 'name': 'Due-date insertion', 'description': 'Whole-prefix insertion scoring.',
            'hypothesis_id': 'hypothesis_pi_command_7a87a57e21b6a87453d4dad3a5f5d325'},
        'swap_insert_restarts': {
            'module': swap_search, 'name': 'Swap/insert restarts', 'description': 'Random first strict improvement and restarts.',
            'hypothesis_id': 'hypothesis_pi_command_f8872b4f838364d5f119c6cb0c790113'},
    }

    def validate(self, name, instance, parameters):
        if parameters:
            raise ValueError('no parameters supported; restart threshold is the bundled default')
        if instance.primary_objective.direction != 'minimize':
            raise ValueError('minimizing objective required')
