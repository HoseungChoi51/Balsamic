// A test extension whose session_start fails: the error must reach the agent's journal.
export default function (pi) {
  pi.on('session_start', () => { throw new Error('broken on purpose'); });
}
