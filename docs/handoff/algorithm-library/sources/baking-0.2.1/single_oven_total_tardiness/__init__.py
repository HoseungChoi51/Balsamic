"""Reusable scheduling algorithms, with no campaign data imported."""
__version__ = '0.2.1'
from .common import Result, recalculate
from .subset_dp import solve as subset_dp
from .due_date_insertion import solve as due_date_insertion
from .swap_search import solve as swap_search
