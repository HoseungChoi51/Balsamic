# Pi dev profile

The Pi agent directory used in dev mode, both by `scripts/pi-dev` (standalone Pi CLI) and,
when `deploy/*.json` sets `"pi_profile": "agent-harness/profiles/dev"`, by the agent harness.
Only configuration is versioned here; Pi's runtime state (sessions, installed packages,
caches, credentials) is ignored by `.gitignore`.

| File | Purpose |
|---|---|
| `settings.json` | Startup defaults (`defaultProvider`, `defaultModel`, optional `defaultThinkingLevel`), pinned `packages`, extension paths |
| `extensions/` | Our own extensions |
| `models.template.json` | The Centinels provider, its endpoint and key named by environment variable (below) |
| `skills/`, `prompts/` | Optional skills and prompt templates |

Provider keys live outside the repository in `~/.config/balsamic/secrets.env`
(`DEEPSEEK_API_KEY=...`, mode 600); override with `BALSAMIC_SECRETS` or `secrets_file`.

## The default model: Centinels

`settings.json` starts agents on `centinels/gpt-6.1-sol`. The `centinels` provider is defined by the tracked
`models.template.json` (an OpenAI-compatible endpoint, `openai-completions`, with `gpt-6.1-sol` and `gpt-6-astra`), which
names its endpoint and key by environment variable. On a fresh checkout, add both to `~/.config/balsamic/secrets.env`:

```
CENTINELS_BASE_URL=https://<the Centinels endpoint>/v1
CENTINELS_API_KEY=<your key>
```

`scripts/start` (and the eval runners) load that file into the harness. The harness resolves the template's `baseUrl`
(Pi itself resolves only the key), merges it under your own `~/.pi/agent/models.json`, where a provider you define
yourself wins, and writes the result to `tmp/models.json` here (ignored). Without `CENTINELS_BASE_URL` the provider is
left out, and a turn on it fails with "Model unavailable: centinels/gpt-6.1-sol. The dev profile defines centinels from
CENTINELS_BASE_URL …", shown in the chat. A `models.json` of your own in this directory replaces the template entirely
and is ignored by git; `auth.json` stays ignored too.

## Workflow

1. Try something interactively: `scripts/pi-dev` (one-off extension: `scripts/pi-dev -e ./ext.ts`).
   Model and thinking level are runtime choices: `/model` (`Ctrl+L`), `/thinking` (`Shift+Tab`).
2. Keep it: `scripts/pi-dev install npm:<package>@<version>` writes a pinned entry to `settings.json`;
   put our own extensions in `extensions/`.
3. Commit the profile change, then restart the service so harness agents load it.

## What dev mode changes in the harness

- Profile extensions, packages and skills load; the application's instructions stay the system
  prompt, context files are not discovered, and Pi's built-in file/shell tools stay off.
- Agents' model and thinking level can be changed at runtime from **Models**, within the
  campaign's model family; a change applies at the agent's next turn.
- Without a profile (locked mode) none of this is configurable.

A campaign is bound to the model family it was activated with (for example `deepseek` or
`openai`). Switching models within that family is allowed; continuing a campaign with another
family is refused. Per-call tokens, cache use and cost are on the **LLM usage** page; API-billed
calls count against the campaign's LLM cap, subscription calls do not.
