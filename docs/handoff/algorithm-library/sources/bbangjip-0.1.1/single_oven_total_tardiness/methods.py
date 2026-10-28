"""H02 exact subset scheduling; no enumeration or swap-search methods."""
from .harness import deterministic
from .objective import order_data

METHODS = {'subset_dp_scheduling': {
    'name': 'Exact subset DP scheduling',
    'description': 'Last-job subset recurrence, deterministic lowest last-index ties.',
    'hypothesis_id': 'hypothesis_pi_command_facb256f0d99495e66d15be195155a9f'}}


def solve(p, d):
    """Return (optimal permutation, value), O(n 2**n) time and O(2**n) space."""
    if len(p) != len(d):
        raise ValueError('processing and due arrays must have the same length')
    size = 1 << len(p)
    sums, costs, last = [0] * size, [0] * size, [-1] * size
    for mask in range(1, size):
        bit = mask & -mask
        sums[mask] = sums[mask ^ bit] + p[bit.bit_length() - 1]
        best = float('inf')
        remaining = mask
        while remaining:
            bit = remaining & -remaining
            j = bit.bit_length() - 1
            cost = costs[mask ^ bit] + max(0, sums[mask] - d[j])
            if cost < best:
                best, last[mask] = cost, j
            remaining ^= bit
        costs[mask] = best
    order, mask = [], size - 1
    while mask:
        j = last[mask]
        order.append(j)
        mask ^= 1 << j
    return order[::-1], costs[-1]


@deterministic
def subset_dp_scheduling(problem, evaluate, rng):
    """method(problem, evaluate, rng), e.g. subset_dp_scheduling(p, callback, rng)."""
    _, p, d, _ = order_data(problem.values)
    candidate, _ = solve(p, d)
    evaluate(candidate)
    return candidate
