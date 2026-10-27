import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// The locked-mode provider is read when the module loads; each query string loads a fresh instance.
async function lockedRuntime(provider) {
  if (provider) process.env.GRATING_PI_PROVIDER = provider; else delete process.env.GRATING_PI_PROVIDER;
  return import(`../dist/runtime.js?provider=${provider || 'none'}`);
}

function signIn(authPath) {
  fs.writeFileSync(authPath, JSON.stringify({'openai-codex': {
    type: 'oauth', access: 'test-access-secret', refresh: 'test-refresh-secret', expires: Date.now() + 3600000,
  }}));
}

test('locked mode offers no provider unless the server names one', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-auth-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const authPath = path.join(directory, 'auth.json');
  t.mock.method(globalThis, 'fetch', () => { throw Error('Auth status must not contact a provider'); });
  signIn(authPath);
  const {authStatus} = await lockedRuntime(null);
  const status = await authStatus(authPath);
  assert.equal(status.configured, false);
  assert.equal(status.provider, null);
  assert.deepEqual(status.models, []);
});

test('status detects persisted login and logout without exposing credentials or using the network', async t => {
  const {authStatus} = await lockedRuntime('openai-codex');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-auth-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const authPath = path.join(directory, 'auth.json');
  t.mock.method(globalThis, 'fetch', () => { throw Error('Auth status must not contact a provider'); });
  fs.writeFileSync(authPath, '{}');
  assert.equal((await authStatus(authPath)).configured, false);
  signIn(authPath);
  const status = await authStatus(authPath);
  assert.equal(status.configured, true);
  assert.equal(status.provider, 'openai-codex');
  assert.ok(status.models.some(m => m.id === 'gpt-6-astra' && m.provider === 'openai-codex'));
  assert.equal(status.providers['openai-codex'].billing, 'subscription');
  // Each model lists the levels Pi's /thinking offers and the one a session runs at when none is chosen.
  assert.ok(status.models.every(m => m.thinking_levels.includes(m.thinking_default)));
  assert.ok(!JSON.stringify(status).includes('secret'));
  fs.writeFileSync(authPath, '{}');
  assert.equal((await authStatus(authPath)).configured, false);
});

test('custom providers come from the profile\'s models.json, else the researcher\'s own Pi configuration', async t => {
  const {modelsFile} = await import('../dist/runtime.js');
  const saved = {file: process.env.GRATING_PI_MODELS_FILE, home: process.env.HOME};
  t.after(() => { if (saved.file === undefined) delete process.env.GRATING_PI_MODELS_FILE; else process.env.GRATING_PI_MODELS_FILE = saved.file; process.env.HOME = saved.home; });
  process.env.GRATING_PI_MODELS_FILE = '/tmp/explicit-models.json';
  assert.equal(modelsFile(), '/tmp/explicit-models.json');
  delete process.env.GRATING_PI_MODELS_FILE;
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-home-')); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  process.env.HOME = home;
  const own = path.join(home, '.pi', 'agent', 'models.json');
  const {profile} = await import('../dist/runtime.js');
  if (profile) {
    if (fs.existsSync(path.join(profile, 'models.json'))) assert.equal(modelsFile(), path.join(profile, 'models.json'));
    else {
      assert.equal(modelsFile(), path.join(profile, 'models.json'), 'no file anywhere: the profile path, so Pi starts with its built-in providers');
      fs.mkdirSync(path.dirname(own), {recursive: true}); fs.writeFileSync(own, '{"providers":{}}');
      assert.equal(modelsFile(), own);
    }
  } else assert.equal(modelsFile(), undefined);
});

test('the dev profile\'s catalogue defines centinels from the environment, under the researcher\'s own providers', async t => {
  const {profileModels, unavailable} = await import('../dist/runtime.js');
  const shipped = JSON.parse(fs.readFileSync(new URL('../profiles/dev/models.template.json', import.meta.url), 'utf8'));
  const settings = JSON.parse(fs.readFileSync(new URL('../profiles/dev/settings.json', import.meta.url), 'utf8'));
  assert.ok(shipped.providers[settings.defaultProvider].models.some(model => model.id === settings.defaultModel), 'the default model is in the catalogue');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-profile-')); t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'pi-home-')); t.after(() => fs.rmSync(home, {recursive: true, force: true}));
  fs.copyFileSync(new URL('../profiles/dev/models.template.json', import.meta.url), path.join(directory, 'models.template.json'));
  fs.mkdirSync(path.join(home, '.pi', 'agent'), {recursive: true});
  fs.writeFileSync(path.join(home, '.pi', 'agent', 'models.json'), JSON.stringify({providers: {strixhalo: {baseUrl: 'http://localhost:8084/v1', api: 'openai-completions'}}}));
  const env = {CENTINELS_BASE_URL: 'https://centinels.example/v1', CENTINELS_API_KEY: 'k'};
  const resolved = profileModels(directory, home, env);
  const written = JSON.parse(fs.readFileSync(resolved.file, 'utf8'));
  assert.equal(resolved.file, path.join(directory, 'tmp', 'models.json'));
  assert.equal(written.providers.centinels.baseUrl, 'https://centinels.example/v1');
  assert.equal(written.providers.centinels.apiKey, '$CENTINELS_API_KEY', 'the key stays a reference Pi resolves at request time');
  assert.equal(written.providers.strixhalo.baseUrl, 'http://localhost:8084/v1', 'the researcher\'s own providers stay');
  assert.deepEqual(resolved.unset, {});
  // Unset: the provider is left out, and a turn on it says what to set.
  const bare = profileModels(directory, home, {});
  assert.equal(JSON.parse(fs.readFileSync(bare.file, 'utf8')).providers.centinels, undefined);
  assert.deepEqual(bare.unset, {centinels: ['CENTINELS_BASE_URL', 'CENTINELS_API_KEY']});
  const saved = process.env.HOME; process.env.HOME = home; t.after(() => { process.env.HOME = saved; });
  assert.match(unavailable('centinels', 'gpt-6.1-sol', directory, {}), /^Model unavailable: centinels\/gpt-6\.1-sol\. The dev profile defines centinels from CENTINELS_BASE_URL and CENTINELS_API_KEY, which are not set: add them to ~\/\.config\/balsamic\/secrets\.env/);
  assert.equal(unavailable('deepseek', 'v4', directory, {}), 'Model unavailable: deepseek/v4');
  // A centinels the researcher defines themselves wins over the catalogue.
  fs.writeFileSync(path.join(home, '.pi', 'agent', 'models.json'), JSON.stringify({providers: {centinels: {baseUrl: 'https://mine.example/v1', api: 'openai-responses'}}}));
  const mine = profileModels(directory, home, {});
  assert.equal(JSON.parse(fs.readFileSync(mine.file, 'utf8')).providers.centinels.baseUrl, 'https://mine.example/v1');
  assert.deepEqual(mine.unset, {});
});

test('a session runs at the chosen thinking level, else at the level Pi gives a new session, within what the model offers', async () => {
  const {thinkingFor} = await import('../dist/runtime.js');
  const settings = (byModel, fallback) => ({getModelThinkingLevel: () => byModel, getDefaultThinkingLevel: () => fallback});
  // A catalogue entry that names only the levels above high (the researcher's gpt-6.1-sol): Pi offers every level up to max.
  const sol = {provider: 'centinels', id: 'gpt-6.1-sol', reasoning: true, thinkingLevelMap: {xhigh: 'xhigh', max: 'max'}};
  assert.equal(thinkingFor(settings(), sol, 'high'), 'high');
  assert.equal(thinkingFor(settings(), sol, 'max'), 'max');
  assert.equal(thinkingFor(settings(), sol, null), 'medium');           // Pi's own default, for new and resumed sessions alike
  assert.equal(thinkingFor(settings(undefined, 'low'), sol), 'low');     // the settings' default
  assert.equal(thinkingFor(settings('xhigh', 'low'), sol), 'xhigh');     // the settings' level for this model comes first
  // A level the model refuses moves up to the next one it offers; a model without reasoning runs at off.
  assert.equal(thinkingFor(settings(), {...sol, thinkingLevelMap: {...sol.thinkingLevelMap, minimal: null}}, 'minimal'), 'low');
  assert.equal(thinkingFor(settings(), {...sol, thinkingLevelMap: {}}, 'max'), 'high');
  assert.equal(thinkingFor(settings(), {provider: 'centinels', id: 'loki'}, 'high'), 'off');
});
