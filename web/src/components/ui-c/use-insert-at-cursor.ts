import { useLayoutEffect, useRef, type RefObject } from 'react';

/**
 * Types text into a controlled field where its cursor is (or over what's selected), then puts the
 * cursor after it: the Edit layout modal's Insert chips (web-ui.md § Files, "chips that type a
 * placeholder at the cursor").
 *
 *   const field = useRef<HTMLInputElement>(null);
 *   const insert = useInsertAtCursor(field, pattern, setPattern);
 *   <TextInput ref={field} value={pattern} onChange={(e) => setPattern(e.target.value)} />
 *   <InsertChips items={['{title}', ...]} onInsert={insert} />
 */
export function useInsertAtCursor(
  field: RefObject<HTMLInputElement | null>,
  value: string,
  setValue: (value: string) => void,
): (text: string) => void {
  // Where the cursor goes once React has drawn the new value (a ref: it isn't drawn itself).
  const caret = useRef<number | null>(null);

  useLayoutEffect(() => {
    const input = field.current;
    if (caret.current === null || !input) return;
    input.focus();
    input.setSelectionRange(caret.current, caret.current);
    caret.current = null;
  });

  return (text: string) => {
    const input = field.current;
    const start = input?.selectionStart ?? value.length;
    const end = input?.selectionEnd ?? start;
    caret.current = start + text.length;
    setValue(value.slice(0, start) + text + value.slice(end));
  };
}
