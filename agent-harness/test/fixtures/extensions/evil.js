// Placed in ~/.pi and in the working directory by the tests: it must never load in a Balsamic session.
import fs from 'node:fs';
import path from 'node:path';
export default function () { const dir = process.env.BALSAMIC_TEST_MARKERS; if (dir) fs.writeFileSync(path.join(dir, 'evil-loaded'), 'x'); }
