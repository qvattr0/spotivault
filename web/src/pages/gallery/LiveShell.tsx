import { ArrowLeft, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { SCENARIOS, type Scenario } from '@mock/fixtures.ts';
import { useSocketState, useStatus } from '@/state';
import { currentScenario, RUN_ACTIONS, setScenario } from './mock-controls.ts';
import { ScaledFrame } from './ScaledFrame.tsx';
import { SCREEN_SIZE, SHELL_SCREENS, type ShellScreen } from './screens.ts';
import styles from './LiveShell.module.css';

/**
 * /gallery?view=shell: the real app in a 1440 × 960 frame (an iframe), live over its own
 * WebSocket, with buttons that set the mock up like a drawing and drive a run. The drawing's PNG
 * can be laid over the frame; the dev server serves web/design-reference/, a build doesn't.
 *
 * Cautious: without a mock backend (SPOTIVAULT_BACKEND set, or the controller serving the build)
 * every control is off, so the gallery never starts a run on a real controller.
 */
export function LiveShell() {
  const [params, setParams] = useSearchParams();
  // The drawing picked last. Until one is, the frame shows the first one's route as the mock is.
  const chosen = params.get('screen');
  const screen = SHELL_SCREENS.find((s) => s.node === chosen) ?? SHELL_SCREENS[0];
  const [scenario, setScenarioName] = useState<Scenario | null | 'checking'>('checking');
  const [reloads, setReloads] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [overlay, setOverlay] = useState(0);
  const [referenceFor, setReferenceFor] = useState<string | null>(null);
  const status = useStatus();
  const socket = useSocketState();

  useEffect(() => {
    let mounted = true;
    void currentScenario().then((found) => mounted && setScenarioName(found));
    return () => {
      mounted = false;
    };
  }, []);

  const hasMock = scenario !== null && scenario !== 'checking';

  async function act(label: string, action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
      setMessage(`${label}: sent.`);
    } catch (error) {
      setMessage(`${label}: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  function startScenario(next: Scenario, label: string) {
    return act(label, async () => {
      await setScenario(next);
      setScenarioName(next);
      // Reload the frame, so the setup gate decides again in the new scenario.
      setReloads((n) => n + 1);
    });
  }

  function show(next: ShellScreen) {
    setParams({ view: 'shell', screen: next.node }, { replace: true });
    void startScenario(next.scenario, next.title);
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <Link to="/gallery" className={styles.back}>
          <ArrowLeft size={16} aria-hidden /> Components
        </Link>
        <h1 className={styles.title}>Shell, live</h1>
        <p className={styles.lede}>
          The app at <code>{screen.path}</code>, in a 1440 × 960 frame like the drawings, live against the
          backend. Pick a drawing to start the mock in the scenario that matches it.
        </p>
      </header>

      <div className={styles.controls} role="group" aria-label="Drawings">
        <span className={styles.groupLabel}>Drawing</span>
        {SHELL_SCREENS.map((s) => (
          <button
            key={s.node}
            type="button"
            className={styles.button}
            aria-pressed={s.node === chosen}
            disabled={!hasMock || busy}
            onClick={() => show(s)}
          >
            {s.title} <span className={styles.node}>{s.node}</span>
          </button>
        ))}
      </div>

      <div className={styles.controls} role="group" aria-label="Run">
        <span className={styles.groupLabel}>Run</span>
        {RUN_ACTIONS.map((action) => (
          <button
            key={action.label}
            type="button"
            className={styles.button}
            disabled={!hasMock || busy}
            onClick={() => void act(action.label, action.run)}
          >
            {action.label}
          </button>
        ))}
        <label className={styles.field}>
          Scenario
          <select
            className={styles.select}
            value={hasMock ? scenario : ''}
            disabled={!hasMock || busy}
            onChange={(event) => {
              const next = event.target.value as Scenario;
              void startScenario(next, `Scenario ${next}`);
            }}
          >
            {!hasMock && <option value="">none</option>}
            {SCENARIOS.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <p role="status" className={styles.status}>
        {scenario === null
          ? 'No mock backend answers /__mock, so the controls are off. The frame still shows the live app.'
          : message}
      </p>

      <div className={styles.readouts}>
        <p className={styles.readout} data-testid="gallery-run-state" data-run-state={status?.state ?? 'unknown'}>
          This page's own live store: socket {socket} · run {status?.state ?? 'unknown'}
          {status?.run ? ` (run ${status.run.id})` : ''}
        </p>
        {referenceFor === screen.node && (
          <label className={styles.field}>
            Drawing over the frame
            <input
              type="range"
              min={0}
              max={100}
              step={10}
              value={overlay}
              onChange={(event) => setOverlay(Number(event.target.value))}
            />
            {overlay} %
          </label>
        )}
        <a className={styles.back} href={screen.path} target="_blank" rel="noreferrer">
          Open in a tab <ExternalLink size={14} aria-hidden />
        </a>
      </div>

      <ScaledFrame width={SCREEN_SIZE.width} height={SCREEN_SIZE.height}>
        <iframe key={`${screen.node}-${reloads}`} title="Live shell" src={screen.path} className={styles.frame} />
        <img
          src={`/design-reference/${screen.node}.png`}
          alt=""
          className={styles.reference}
          style={{ opacity: overlay / 100 }}
          onLoad={() => setReferenceFor(screen.node)}
          onError={() => setReferenceFor(null)}
        />
      </ScaledFrame>
    </main>
  );
}
