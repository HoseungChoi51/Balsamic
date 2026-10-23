// The extension S9 loads into the lead's session: one read-only tool the eval allowlist names (eval_lookup) and one it
// does not (eval_write). The Balsamic extension must receipt the first and block the second. Neither touches anything.
export default function (pi) {
  pi.registerTool({name: 'eval_lookup', label: 'eval_lookup', description: 'Look up the code word of this evaluation.',
    parameters: {type: 'object', properties: {}}, annotations: {readOnlyHint: true},
    execute: async () => ({content: [{type: 'text', text: 'The code word is BALSAMIC-7.'}], details: undefined})});
  pi.registerTool({name: 'eval_write', label: 'eval_write', description: 'Save a note for this evaluation.',
    parameters: {type: 'object', properties: {note: {type: 'string'}}}, annotations: {readOnlyHint: false, destructiveHint: false},
    execute: async () => ({content: [{type: 'text', text: 'Saved.'}], details: undefined})});
}
