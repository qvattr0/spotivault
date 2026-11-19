// Copying text to the clipboard: step 5's redirect URI and History's "Copy path".
//
// The clipboard API needs a secure page (HTTPS or localhost), and spotivault is usually opened
// over plain http on the LAN (http://<nas>:8080). There the old way is used: select the text and
// run the browser's copy command.

/**
 * Copies `text`. Resolves to whether it worked.
 *
 * `field` is an input already showing the text (step 5's read-only field): it's selected for the
 * old way, so the user also sees what was copied. Without one, a hidden text box is used for a
 * moment, and focus goes back where it was.
 */
export async function copyText(text: string, field: HTMLInputElement | null = null): Promise<boolean> {
  try {
    if (window.isSecureContext && navigator.clipboard) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Refused: fall back to the copy command.
  }
  if (field) {
    field.focus();
    field.select();
    return runCopyCommand();
  }
  return copyThroughHiddenBox(text);
}

function copyThroughHiddenBox(text: string): boolean {
  const before = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const box = document.createElement('textarea');
  box.value = text;
  box.setAttribute('readonly', '');
  box.setAttribute('aria-hidden', 'true');
  // Off screen, but still selectable (display: none can't be selected).
  box.style.position = 'fixed';
  box.style.top = '0';
  box.style.left = '-9999px';
  box.style.opacity = '0';
  // Inside an open dialog, so the dialog's focus trap leaves it alone.
  const host = before?.closest('[aria-modal="true"]') ?? document.body;
  host.appendChild(box);
  box.focus();
  box.select();
  const copied = runCopyCommand();
  box.remove();
  before?.focus();
  return copied;
}

function runCopyCommand(): boolean {
  try {
    return document.execCommand('copy');
  } catch {
    return false;
  }
}
