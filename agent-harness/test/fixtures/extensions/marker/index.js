// A test extension: records that it loaded and that its session started and ended, and offers one read-only tool.
import fs from 'node:fs';
import path from 'node:path';

const mark = (name) => { const dir = process.env.BALSAMIC_TEST_MARKERS; if (dir) fs.writeFileSync(path.join(dir, name), String(Date.now())); };
export default function (pi) {
  (globalThis.__balsamicOrder ||= []).push('marker:load');
  pi.on('session_start', () => { (globalThis.__balsamicOrder ||= []).push('marker:start'); mark('marker-started'); });
  pi.on('session_shutdown', () => { mark('marker-shutdown'); });
  pi.registerTool({name: 'marker_lookup', label: 'marker_lookup', description: 'Look up a marker.', parameters: {type: 'object', properties: {}},
    annotations: {readOnlyHint: true}, execute: async () => ({content: [{type: 'text', text: 'marker'}], details: undefined})});
}
