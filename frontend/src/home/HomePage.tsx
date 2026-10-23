/** The landing page at the bare address: the logo, the name, the version and what Balsamic is. */
import { version } from '../../package.json';

/** A balsamic drop garnished with basil; inside, a descent settling at its minimum. Colors are the --logo-* tokens. */
export function Logo({ size = 148 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size * 116 / 112} viewBox="16 4 112 116" role="img" aria-label="Balsamic logo" data-testid="home-logo">
      <path className="leaf" d="M78 106 C84 80 98 64 120 56 C119 82 104 102 78 106 Z" />
      <path className="vein" d="M78 106 Q100 84 120 56" />
      <path className="leaf-2" d="M82 110 C94 104 108 104 122 112 C110 120 94 120 82 110 Z" />
      <path className="drop" d="M56 8 C50 28 22 52 22 80 A34 34 0 0 0 90 80 C90 52 62 28 56 8 Z" />
      <path className="shine" d="M35 66 C36 58 40 50 46 43" />
      <path className="descent" d="M36 80 C44 100 62 103 78 84" />
      <circle className="minimum" cx="54" cy="96" r="5" />
    </svg>
  );
}

export function HomePage() {
  return (
    <main className="home" data-testid="home">
      <Logo />
      <h1 className="home-name">Balsamic</h1>
      <span className="pill mono" data-testid="home-version">v{version}</span>
      <p className="home-about">A research workspace in which you and a lead agent develop an effective optimizer for the problem at hand.</p>
      <a className="btn primary" href="#monitor" data-testid="home-open">Open the workspace</a>
    </main>
  );
}
