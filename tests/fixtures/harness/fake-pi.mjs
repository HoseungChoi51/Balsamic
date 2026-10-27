// A stand-in for the pi binary in the harness adapter's tests (roadmap H2). It replays a recorded `pi --mode json` stream
// (FAKE_PI_STREAM): headless, on stdout, after reading its instruction from stdin; as the terminal UI, into the extension
// it is given (--extension), calling its handlers with the stream's session events the way Pi calls them. FAKE_PI_LOG, when
// set, records how it was called.
import fs from 'node:fs';
import module from 'node:module';
import {pathToFileURL} from 'node:url';

const args = process.argv.slice(2);
const option = name => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : undefined; };
const stream = fs.readFileSync(process.env.FAKE_PI_STREAM, 'utf8');
const log = entry => { if (process.env.FAKE_PI_LOG) fs.appendFileSync(process.env.FAKE_PI_LOG, JSON.stringify(entry) + '\n'); };

if (option('--mode') === 'json') {
  log({mode: 'json', args, input: fs.readFileSync(0, 'utf8'), harness_mode: process.env.BALSAMIC_HARNESS_MODE});
  process.stdout.write(stream);
} else {
  // Pi gives its extensions these two packages; the fake gives the little of them the extension uses at load.
  const stubs = {
    '@earendil-works/pi-ai': 'export const Type = new Proxy({}, {get: () => (...args) => ({args})}); export const StringEnum = values => ({enum: values});',
    '@earendil-works/pi-coding-agent': 'export const defineTool = tool => tool;',
  };
  module.registerHooks({resolve: (specifier, context, next) => stubs[specifier]
    ? {url: 'data:text/javascript,' + encodeURIComponent(stubs[specifier]), shortCircuit: true} : next(specifier, context)});
  const extension = (await import(pathToFileURL(option('--extension')).href)).default;
  const handlers = {}, delivered = [];
  extension({registerTool() {}, registerCommand() {}, on: (name, handler) => { (handlers[name] ||= []).push(handler); }, appendEntry() {},
    sendUserMessage: (text, options) => { delivered.push({text, ...options}); }, abort() {},
    getActiveTools: () => ['read', 'bash', 'edit', 'write', 'campaign_checkpoint', 'campaign_submit']});
  const fire = async (name, event, ctx) => { for (const handler of handlers[name] || []) await handler(event, ctx); };
  await fire('session_start', {type: 'session_start'}, {sessionManager: {getSessionFile: () => option('--session'), getEntries: () => []}});
  for (const line of stream.split('\n')) {
    if (line.trim()) await fire(JSON.parse(line).type, JSON.parse(line));
  }
  await fire('session_shutdown', {type: 'session_shutdown'});
  log({mode: 'tui', args, delivered, harness_mode: process.env.BALSAMIC_HARNESS_MODE});
}
