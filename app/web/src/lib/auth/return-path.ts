import { CONSOLE_BASE_PATH, consolePath } from "@/lib/base-path";

export function consoleReturnPath(value: string | null): string {
  const fallback = consolePath("/dashboard");
  if (!value || value.length > 2048 || /[\x00-\x1f\x7f]/.test(value))
    return fallback;
  const rawPath = value.split(/[?#]/, 1)[0];
  if (!(
    rawPath === CONSOLE_BASE_PATH || rawPath.startsWith(`${CONSOLE_BASE_PATH}/`)
  ))
    return fallback;
  let path: string;
  try {
    path = decodeURIComponent(rawPath);
  } catch {
    return fallback;
  }
  if (
    !(path === CONSOLE_BASE_PATH || path.startsWith(`${CONSOLE_BASE_PATH}/`)) ||
    /[\\%\x00-\x1f\x7f]/.test(path) ||
    path.split("/").some((segment) => segment === "." || segment === "..") ||
    path.replace(/\/+$/, "") === consolePath("/login")
  )
    return fallback;
  return value;
}
