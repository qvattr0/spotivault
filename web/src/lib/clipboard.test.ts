import { afterEach, describe, expect, it, vi } from 'vitest';
import { copyText } from './clipboard.ts';

/** Stands in for the browser's copy command, and remembers what was selected when it ran. */
function fakeCopyCommand() {
  const copied: string[] = [];
  const execCommand = vi.fn(() => {
    const active = document.activeElement;
    if (active instanceof HTMLTextAreaElement || active instanceof HTMLInputElement) {
      copied.push(active.value.slice(active.selectionStart ?? 0, active.selectionEnd ?? 0));
    }
    return true;
  });
  Object.defineProperty(document, 'execCommand', { value: execCommand, configurable: true });
  return { execCommand, copied };
}

function setSecure(secure: boolean, clipboard: Pick<Clipboard, 'writeText'> | undefined) {
  vi.stubGlobal('isSecureContext', secure);
  Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = '';
});

describe('copyText', () => {
  it('uses the clipboard API on a secure page', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    setSecure(true, { writeText });
    const { execCommand } = fakeCopyCommand();
    expect(await copyText('Music/a.m4a')).toBe(true);
    expect(writeText).toHaveBeenCalledWith('Music/a.m4a');
    expect(execCommand).not.toHaveBeenCalled();
  });

  it('over plain http, copies through a hidden box and gives focus back', async () => {
    setSecure(false, undefined);
    const { copied } = fakeCopyCommand();
    const button = document.createElement('button');
    document.body.appendChild(button);
    button.focus();

    expect(await copyText('Music/Playlists/Chill Mix/01 - Last Hours.m4a')).toBe(true);
    expect(copied).toEqual(['Music/Playlists/Chill Mix/01 - Last Hours.m4a']);
    expect(document.activeElement).toBe(button);
    expect(document.querySelector('textarea')).toBeNull();
  });

  it('selects the field it was given, so the user sees what was copied', async () => {
    setSecure(false, undefined);
    const { copied } = fakeCopyCommand();
    const field = document.createElement('input');
    field.value = 'http://127.0.0.1:8888/callback';
    document.body.appendChild(field);

    expect(await copyText(field.value, field)).toBe(true);
    expect(copied).toEqual(['http://127.0.0.1:8888/callback']);
    expect(document.activeElement).toBe(field);
  });

  it('says so when the browser refuses both ways', async () => {
    setSecure(true, { writeText: () => Promise.reject(new Error('denied')) });
    Object.defineProperty(document, 'execCommand', { value: () => false, configurable: true });
    expect(await copyText('x')).toBe(false);
  });
});
