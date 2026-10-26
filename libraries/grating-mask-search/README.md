# grating-mask-search

Three binary-mask search methods for the 2D silicon/air dual-polarization beam deflector
(`meent_2d_dual_polarization_deflector`, a 128 × 256 mask), offered to Balsamic as optimizer plug-ins. Each is an
implementation of a campaign proposal. Whether a method is any good is for experiments and the researcher to judge;
this library only claims that each module implements the specification in `docs/`.

| Method id | Module | Proposal | Specification |
|---|---|---|---|
| `cyclic_geometric_vnd` | `cyclic_geometric_vnd.py` | H12, Cyclic variable-neighborhood descent with geometric displacement | `docs/cyclic_geometric_vnd.md` |
| `conditional_mirror_search` | `conditional_mirror_search.py` | H13, Frozen-batch conditional mirror search with bounded active windows | `docs/conditional_mirror_search.txt` |
| `elite_spread_relinking` | `elite_spread_relinking.py` | H14, Elite-plus-spread archive relinking on full binary masks | `docs/elite_spread_relinking.md` |

The modules use the standard library only and know nothing of Balsamic: each follows the `optimizer_v1` package
contract (`create_optimizer(context)`, then `initialize`, `propose`, `observe`, `checkpoint` as bytes, `restore`,
`inspect`). `plugin.py` is the adapter: it lists the methods for Balsamic's `optimization_framework.optimizers`
entry point and runs each module through `optimization_framework.optimizers.packaged`.

## Tests

```bash
uv run pytest libraries/grating-mask-search    # from the repository root, once installed (below)
```

- `tests/test_<method>.py`: the implementer's own tests of each method against its specification.
- `tests/test_contract.py`: Balsamic's optimizer contract on the deflector problem, without a solver: valid
  candidates, seeded replay, checkpoint continuation, and JSON checkpoints and inspection
  (`optimization_framework.optimizers.conformance`).

## Install

The repository pins the library as a path dependency (`libraries` extra in the root `pyproject.toml`). After
`uv sync --inexact --extra libraries` the running lab picks it up at its next listing, without a restart: the three
method ids are available to every campaign on the deflector problem, and a proposal runs one by binding it
(`implementation.bind_builtin`).

## Provenance

Built in the 2d-gratnig campaign's coding workspaces on 2026-10-25/26 and copied here unchanged, apart from the
tests' import lines:

| Method | Workspace | Commit |
|---|---|---|
| `cyclic_geometric_vnd` | `development_0e9073fe4f8fb2ed6c119f74` | `704ea986336fc9aa340797ea40bc4157391de481` |
| `conditional_mirror_search` | `development_cc3011800df507cd253d4300` | `7663208c7a5c372bd105603bfd2a524fc7205a7e` |
| `elite_spread_relinking` | `development_f12a004151022c27e9442e20` | `5378e120450d5dbf15100ce4e650c608afba23e0` |
