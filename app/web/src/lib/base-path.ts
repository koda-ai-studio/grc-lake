/**
 * Path prefix the console is served under. Next adds it to router links but
 * not to raw asset URLs, so those use this. `/console` is the Python server
 * mount; the static live demo builds under its hosting path instead.
 */
export const CONSOLE_BASE_PATH =
  process.env.NEXT_PUBLIC_CONSOLE_BASE_PATH || "/console";

export function consolePath(path: string): string {
  return `${CONSOLE_BASE_PATH}${path}`;
}
