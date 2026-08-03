/**
 * Formats seconds for display only. Never use the result for logic/comparisons -
 * always keep and compare the raw float value from the API.
 */
export function formatSeconds(seconds: number): string {
  return `${seconds.toFixed(1)}с`
}
