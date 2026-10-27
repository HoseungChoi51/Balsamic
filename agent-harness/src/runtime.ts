import { clampThinkingLevel, getSupportedThinkingLevels } from '@earendil-works/pi-ai';
import { createAgentSession, createExtensionRuntime, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager } from '@earendil-works/pi-coding-agent';
import fs from 'node:fs';
import path from 'node:path';

// Locked mode (no profile): nothing is discovered (no host extensions, skills or repository instructions); only the
// curated extensions the manifest names for the agent's role load, after the Balsamic extension, and every tool that
// acts is the application gateway's or receipted by it (gateway-extension.ts).
// Dev mode (GRATING_PI_PROFILE names an agent directory): that profile's settings, packages, extensions and skills
// load too, so Pi configurations can be tried without changing Balsamic; the Balsamic extension still loads first.
// An implementation grant's roles get no extensions in either mode. Pi's built-in file/shell tools stay off.
// Sessions recorded before the provider was stored all used the OpenAI Codex subscription.
export const LEGACY_PROVIDER = 'openai-codex';
// Locked mode offers exactly one provider, and only when the server names it: no default provider.
export const LOCKED_PROVIDER = process.env.GRATING_PI_PROVIDER || null;
export const profile = process.env.GRATING_PI_PROFILE ? path.resolve(process.env.GRATING_PI_PROFILE) : null;
export const BALSAMIC = 'balsamic';
const OVERRIDES = {compaction: {enabled: true, reserveTokens: 16384, keepRecentTokens: 20000},
  retry: {enabled: true, maxRetries: 3, baseDelayMs: 2000}};
// Pi's own level for a new session when its settings name none (DEFAULT_THINKING_LEVEL, not exported).
const PI_DEFAULT_THINKING = 'medium';

/**
 * The thinking level a session runs at: the one Balsamic names, else what Pi gives a new session (the settings' level
 * for the model, their default, then Pi's), clamped to the model's levels as Pi does. Every session, new or resumed, is
 * given its level, so "default" is one level, not whatever a resumed session last recorded.
 */
export function thinkingFor(settings: any, model: any, effort?: string | null) {
  return clampThinkingLevel(model, (effort || settings.getModelThinkingLevel(model.provider, model.id)
    || settings.getDefaultThinkingLevel() || PI_DEFAULT_THINKING) as any);
}

function settingsFor(directory?: string) {
  return profile ? SettingsManager.create(directory || profile, profile) : SettingsManager.inMemory(OVERRIDES);
}

/**
 * Custom providers (a LiteLLM proxy, a local server) come from a Pi models.json: the profile's own when it has one,
 * else the researcher's own Pi configuration (~/.pi/agent/models.json), so the harness offers the same models as `pi` does.
 * GRATING_PI_MODELS_FILE names another file. Keys stay in auth.json and the environment, never in the profile.
 */
export function modelsFile(): string | undefined {
  if (process.env.GRATING_PI_MODELS_FILE) return path.resolve(process.env.GRATING_PI_MODELS_FILE);
  if (profile && fs.existsSync(path.join(profile, 'models.json'))) return path.join(profile, 'models.json');
  const own = path.join(process.env.HOME || '', '.pi', 'agent', 'models.json');
  return profile && fs.existsSync(own) ? own : profile ? path.join(profile, 'models.json') : undefined;
}

async function modelRuntime(authPath: string) {
  const models = modelsFile();
  return ModelRuntime.create({authPath, refreshOnCreate: false, ...(models ? {modelsPath: models} : {})} as any);
}

export async function createRuntime(options: any) {
  const provider = options.provider || LEGACY_PROVIDER;
  const runtime = await modelRuntime(options.authPath);
  await runtime.refresh({providers: [provider], allowNetwork: false});
  const model = runtime.getModel(provider, options.model);
  if (!model) throw new Error(`Model unavailable: ${provider}/${options.model}`);
  const sessionDir = path.join(options.directory, 'sessions');
  fs.mkdirSync(sessionDir, {recursive: true, mode: 0o700});
  const manager = options.sessionFile ? SessionManager.open(options.sessionFile)
    : SessionManager.create(options.directory, sessionDir);
  const host = options.extensionHost === true;
  const curated = host ? (options.extensions || []) : [];
  const factories = host && options.balsamicExtension ? [{name: BALSAMIC, factory: options.balsamicExtension}] : [];
  // Pi loads inline extensions after the files; the Balsamic extension's handlers must run first.
  const balsamicFirst = (result: any) => ({...result, extensions: [...result.extensions.filter((e: any) => e.path === `<inline:${BALSAMIC}>`),
    ...result.extensions.filter((e: any) => e.path !== `<inline:${BALSAMIC}>`)]});
  const settingsManager: any = settingsFor(options.directory);
  if (profile) settingsManager.applyOverrides(OVERRIDES);
  let resourceLoader: any;
  if (host) {
    const common = {cwd: options.directory, settingsManager, systemPrompt: options.instructions, noContextFiles: true,
      additionalExtensionPaths: curated.map((e: any) => e.path), extensionFactories: factories, extensionsOverride: balsamicFirst};
    if (profile) resourceLoader = new DefaultResourceLoader({...common, agentDir: profile});
    else {
      // An empty agent directory of the session's own: nothing of ~/.pi or of the working directory is read.
      const agentDir = path.join(options.directory, 'pi-agent');
      fs.mkdirSync(agentDir, {recursive: true, mode: 0o700});
      resourceLoader = new DefaultResourceLoader({...common, agentDir, noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true});
    }
    await resourceLoader.reload();
  } else {
    resourceLoader = {
      getExtensions: () => ({extensions: [], errors: [], runtime: createExtensionRuntime()}),
      getSkills: () => ({skills: [], diagnostics: []}), getPrompts: () => ({prompts: [], diagnostics: []}),
      getThemes: () => ({themes: [], diagnostics: []}), getAgentsFiles: () => ({agentsFiles: []}),
      getSystemPrompt: () => options.instructions, getSystemPromptSource: () => undefined,
      getAppendSystemPrompt: () => [], getAppendSystemPromptSources: () => [],
      extendResources: () => {}, reload: async () => {},
    };
  }
  const extensionTools = curated.flatMap((e: any) => e.tools || []);
  const {session, modelFallbackMessage} = await createAgentSession({
    cwd: options.directory, modelRuntime: runtime, model, thinkingLevel: thinkingFor(settingsManager, model, options.effort),
    resourceLoader, customTools: options.tools, sessionManager: manager, settingsManager,
    // Dev profiles may add extension tools; otherwise the gateway's tools and the role's allowlisted extension tools.
    ...(profile && host ? {noTools: 'builtin'} : {tools: [...options.tools.map((t: any) => t.name), ...extensionTools]}),
  } as any);
  if (modelFallbackMessage) { session.dispose(); throw new Error(modelFallbackMessage); }
  // What Pi's RPC and interactive modes do and an SDK host must do itself: fire session_start (extensions start their
  // connections and rebuild their state there), attach the UI, and report extension errors.
  if (host) await session.bindExtensions({uiContext: options.uiContext, mode: 'rpc', onError: options.onExtensionError, shutdownHandler: () => {}});
  (session as any).shutdown = () => shutdown(session);
  const auth = await runtime.checkAuth(provider).catch(() => undefined);
  (session as any).billing = auth?.type === 'oauth' ? 'subscription' : auth?.type === 'api_key' ? 'api' : 'unknown';
  return session;
}

/** session_shutdown for the session's extensions (AgentSession.dispose() does not emit it), then dispose. Idempotent. */
export async function shutdown(session: any) {
  if (session.balsamicShutdown) return;
  session.balsamicShutdown = true;
  const runner = session.extensionRunner;
  try { if (runner?.hasHandlers?.('session_shutdown')) await runner.emit({type: 'session_shutdown', reason: 'quit'}); }
  finally { session.dispose(); }
}

/** Switch an existing session in place; Pi records the change in the session file. */
export async function applySpec(session: any, spec: any) {
  const provider = spec.provider || LEGACY_PROVIDER;
  if (session.model?.provider !== provider || session.model?.id !== spec.model) {
    await session.modelRuntime.refresh({providers: [provider], allowNetwork: false});
    const model = session.modelRuntime.getModel(provider, spec.model);
    if (!model) throw new Error(`Model unavailable: ${provider}/${spec.model}`);
    await session.setModel(model);
    const auth = await session.modelRuntime.checkAuth(provider).catch(() => undefined);
    session.billing = auth?.type === 'oauth' ? 'subscription' : auth?.type === 'api_key' ? 'api' : 'unknown';
  }
  const level = thinkingFor(session.settingsManager, session.model, spec.effort);
  if (session.thinkingLevel !== level) session.setThinkingLevel(level);
}

/**
 * One model call with the saved sign-in, outside any agent session: system text and one prompt in, the reply's text out.
 * The stream is passed to `observe` as it arrives, so the caller can show the reasoning without keeping it.
 */
export async function completeOnce(authPath: string, input: any, observe: (event: any) => void, signal?: AbortSignal) {
  const provider = input.provider || LEGACY_PROVIDER;
  const runtime = await modelRuntime(authPath);
  await runtime.refresh({providers: [provider], allowNetwork: false});
  const model = runtime.getModel(provider, input.model);
  if (!model) throw new Error(`Model unavailable: ${provider}/${input.model}`);
  const auth = await runtime.checkAuth(provider).catch(() => undefined);
  if (!auth) throw new Error(`No sign-in or key is configured for ${provider}`);
  const level = thinkingFor(settingsFor(), model, input.effort);
  const stream = runtime.streamSimple(model, {systemPrompt: String(input.system || ''),
    messages: [{role: 'user', content: String(input.prompt || ''), timestamp: Date.now()}]},
    {...(level !== 'off' ? {reasoning: level} : {}), ...(input.max_tokens ? {maxTokens: input.max_tokens} : {}), signal} as any);
  for await (const event of stream) observe({type: 'message_update', assistantMessageEvent: event});
  const message: any = await stream.result();
  if (message.stopReason === 'error' || message.stopReason === 'aborted') throw new Error(message.errorMessage || 'Provider request failed');
  const usage: any = Object.fromEntries(['input', 'output', 'cacheRead', 'cacheWrite', 'reasoning', 'totalTokens'].map(key => [key, message.usage?.[key] || 0]));
  usage.cost_usd = message.usage?.cost?.total || 0;
  return {text: message.content.filter((part: any) => part.type === 'text').map((part: any) => part.text).join('\n'), usage,
    stop_reason: message.stopReason, provider: message.provider || provider, model: message.model || input.model, thinking_level: level,
    billing: auth.type === 'oauth' ? 'subscription' : auth.type === 'api_key' ? 'api' : 'unknown', occurred_at: new Date().toISOString()};
}

export async function authStatus(authPath: string) {
  const runtime = await modelRuntime(authPath);
  // checkAuth reads persisted credentials and the environment, also picking up
  // sign-in through the browser or a separate CLI process.
  const providers: Record<string, any> = {};
  const ids = profile ? runtime.getProviders().map((p: any) => p.id) : LOCKED_PROVIDER ? [LOCKED_PROVIDER] : [];
  for (const id of ids) {
    const auth = await runtime.checkAuth(id).catch(() => undefined);
    if (auth) providers[id] = {auth: auth.type, billing: auth.type === 'oauth' ? 'subscription' : 'api'};
  }
  // The levels Pi's /thinking offers for each model, and the one a session runs at when none is chosen.
  const settings = settingsFor();
  const models = Object.keys(providers).flatMap(id => runtime.getModels(id).map((m: any) => ({
    provider: id, id: m.id, name: m.name, reasoning: Boolean(m.reasoning), thinking_levels: getSupportedThinkingLevels(m),
    thinking_default: thinkingFor(settings, m),
    context_window: m.contextWindow, max_tokens: m.maxTokens, cost: m.cost})));
  let defaults: any = {provider: LOCKED_PROVIDER, model: null, effort: null};
  if (profile) {
    defaults = {provider: settings.getDefaultProvider() || null, model: settings.getDefaultModel() || null,
      effort: settings.getDefaultThinkingLevel() || null};
  }
  return {configured: Object.keys(providers).length > 0, mode: profile ? 'dev' : 'locked',
    provider: defaults.provider, providers, defaults, models};
}
