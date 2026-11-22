/**
 * Joins class names, skipping false, null and undefined:
 *   cx(styles.button, primary && styles.primary, className)
 */
export function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(' ');
}
