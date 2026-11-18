// The body of wizard step 5 and of the Reconnect flow (web-ui.md § 5; j8m6AR):
//   1. Create an app in the Spotify developer dashboard, with the redirect URI (and a Copy button).
//   2. Paste the app's Client ID (POST /api/spotify/app).
//   3. Authorize: open Spotify's consent page in a new tab (POST /api/spotify/auth/start), approve,
//      then paste the address of the error page it lands on, and Connect (POST /api/spotify/auth/finish).
//   4. Checks: the token works, and the container's client is a playback device.
//
// Reconnect (`mode="reconnect"`) skips 1 and 2 when a Client ID is stored, unless `changeClientId`
// (/reconnect?change=client_id, Settings' "Change") asks for a new one first.
//
// Secrets: the stored Client ID only ever shows masked (`client_id_masked`); what you type is sent
// once and the field cleared. The pasted address is sent once, and kept nowhere: not in the field
// after Connect, not in the browser's storage.

import { useRef, useState } from 'react';
import { Copy, ExternalLink } from 'lucide-react';
import { api } from '@/api';
import { Button, ButtonLink, TextInput } from '@/components/ui-a';
import { useToast } from '@/components/ui-b';
import { copyText } from '@/lib/clipboard.ts';
import { errorText } from '@/lib/errors.ts';
import { useAction } from '@/lib/use-action.ts';
import { useSetup, useSpotifyConnection } from '@/state';
import { stepDone } from '../parts/step-nav.ts';
import { openBlankTab } from './browser.ts';
import { Checks, isConnected } from './Checks.tsx';
import { Section } from './Section.tsx';
import { AUTH_ERRORS, CLIENT_ID_ERRORS, CLIENT_ID_INVALID, CLIENT_ID_PATTERN, DEVELOPER_DASHBOARD, REDIRECT_URI } from './words.ts';
import styles from './WebApi.module.css';

interface WebApiConnectProps {
  mode: 'wizard' | 'reconnect';
  /** Ask for a new Client ID even though one is stored. */
  changeClientId?: boolean;
}

export function WebApiConnect({ mode, changeClientId = false }: WebApiConnectProps) {
  const connection = useSpotifyConnection();
  const setup = useSetup();
  const toast = useToast();
  const stored = connection?.client_id_masked ?? null;
  const connected = isConnected(connection);

  const [editing, setEditing] = useState(changeClientId);
  const [clientId, setClientId] = useState('');
  const [clientIdError, setClientIdError] = useState<string | null>(null);
  // Shown once Authorize was pressed: "the field this step then shows".
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasted, setPasted] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  // The consent page's address, when the browser blocked the new tab.
  const [blockedUrl, setBlockedUrl] = useState<string | null>(null);
  const redirectField = useRef<HTMLInputElement>(null);

  const askClientId = editing || stored === null;
  const saveApp = useAction((id: string) => api.POST('/api/spotify/app', { body: { client_id: id } }), {
    onError: (error) => setClientIdError(errorText(error, CLIENT_ID_ERRORS)),
  });
  const start = useAction(() => api.POST('/api/spotify/auth/start'), {
    onError: (error) => setAuthError(errorText(error, AUTH_ERRORS)),
  });
  const finish = useAction((url: string) => api.POST('/api/spotify/auth/finish', { body: { redirect_url: url } }), {
    onError: (error) => setAuthError(errorText(error, AUTH_ERRORS)),
  });

  async function authorize() {
    setAuthError(null);
    setClientIdError(null);
    const id = clientId.trim().toLowerCase();
    if (askClientId && !CLIENT_ID_PATTERN.test(id)) {
      setClientIdError(CLIENT_ID_INVALID);
      return;
    }
    // Opened now, inside the click, so the browser lets it through; it goes to Spotify below.
    const tab = openBlankTab();
    if (askClientId) {
      const saved = await saveApp.run(id);
      if (!saved || saved.error) {
        tab?.close();
        return;
      }
      setClientId('');
      setEditing(false);
    }
    const started = await start.run();
    if (!started || started.error) {
      tab?.close();
      return;
    }
    setPasteOpen(true);
    if (tab) {
      tab.location.href = started.data.authorize_url;
      setBlockedUrl(null);
    } else {
      setBlockedUrl(started.data.authorize_url);
    }
  }

  async function connect() {
    const url = pasted.trim();
    // Sent once, kept nowhere.
    setPasted('');
    setAuthError(null);
    if (!url) return;
    const result = await finish.run(url);
    if (result && !result.error) {
      setPasteOpen(false);
      setBlockedUrl(null);
    }
  }

  async function copyRedirect() {
    const copied = await copyText(REDIRECT_URI, redirectField.current);
    toast.show(copied ? 'Copied' : 'Select the address and copy it with Ctrl+C');
  }

  // The app and the Client ID: always in the wizard; in the Reconnect flow only when it asks for a
  // Client ID, and then they stay once it's saved. Without them, the sections count from 1.
  const [appStepsShown] = useState(mode === 'wizard' || changeClientId || stored === null);
  const showAppSteps = appStepsShown || askClientId;
  const first = showAppSteps ? 3 : 1;

  return (
    <div className={styles.sections}>
      {showAppSteps ? (
        <Section number={1} title="Create an app in the Spotify developer dashboard" done={stored !== null}>
          <p className={styles.text}>Set this as the app&apos;s redirect URI:</p>
          <div className={styles.fieldRow}>
            <TextInput ref={redirectField} mono readOnly value={REDIRECT_URI} aria-label="Redirect URI" />
            <Button variant="secondary" icon={Copy} onClick={() => void copyRedirect()}>
              Copy
            </Button>
          </div>
          <div className={styles.links}>
            <ButtonLink variant="tertiary" href={DEVELOPER_DASHBOARD}>
              Open developer dashboard
            </ButtonLink>
          </div>
        </Section>
      ) : null}

      {showAppSteps ? (
        <Section number={2} title="Paste the app's Client ID" done={stored !== null && !editing}>
          {askClientId ? (
            <div className={styles.fieldRow}>
              <TextInput
                mono
                aria-label="Client ID"
                placeholder="32 characters, from the app's Basic Information"
                autoComplete="off"
                spellCheck={false}
                value={clientId}
                onChange={(event) => setClientId(event.target.value)}
                error={clientIdError ?? undefined}
                hint={stored !== null ? 'A new Client ID disconnects spotivault until you authorize again.' : undefined}
              />
              {stored !== null ? (
                <Button
                  variant="tertiary"
                  onClick={() => {
                    setEditing(false);
                    setClientId('');
                    setClientIdError(null);
                  }}
                >
                  Cancel
                </Button>
              ) : null}
            </div>
          ) : (
            <div className={styles.fieldRow}>
              <TextInput mono readOnly aria-label="Client ID" value={stored ?? ''} />
              <Button variant="tertiary" onClick={() => setEditing(true)}>
                Change
              </Button>
            </div>
          )}
        </Section>
      ) : null}

      <Section number={first} title="Authorize" done={connected && !pasteOpen}>
        <p className={styles.text}>
          After you approve, the browser lands on an error page at 127.0.0.1:8888. That&apos;s expected. Copy that whole address and paste it
          here.
        </p>
        <div className={styles.links}>
          <Button
            variant="secondary"
            icon={ExternalLink}
            busy={saveApp.busy || start.busy}
            disabled={askClientId && clientId.trim() === ''}
            onClick={() => void authorize()}
          >
            Open Spotify consent page
          </Button>
        </div>
        {blockedUrl ? (
          <p className={styles.blocked} role="status">
            The browser blocked the new tab.{' '}
            <a href={blockedUrl} target="_blank" rel="noreferrer">
              Open Spotify&apos;s consent page
            </a>
            .
          </p>
        ) : null}
        {pasteOpen ? (
          <form
            className={styles.fieldRow}
            onSubmit={(event) => {
              event.preventDefault();
              void connect();
            }}
          >
            <TextInput
              mono
              aria-label="Address of the error page"
              placeholder={`${REDIRECT_URI}?code=…`}
              autoComplete="off"
              spellCheck={false}
              value={pasted}
              onChange={(event) => setPasted(event.target.value)}
              error={authError ?? undefined}
            />
            <Button type="submit" variant="primary" size="sm" busy={finish.busy} disabled={pasted.trim() === ''}>
              Connect
            </Button>
          </form>
        ) : authError ? (
          <p className={styles.blocked} role="alert">
            {authError}
          </p>
        ) : null}
      </Section>

      <Section number={first + 1} title="Checks" done={connected && stepDone(setup, 'webapi')}>
        <Checks connection={connection} mode={mode} />
      </Section>
    </div>
  );
}
