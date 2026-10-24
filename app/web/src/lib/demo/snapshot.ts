/**
 * Static replay of recorded API responses for the read-only live demo.
 *
 * Dependency-free so the recorder (Node) and the console share one key
 * function: a response recorded under a key is found again by the browser.
 */

export const DEMO_MARKER = "grc-lake-demo-snapshot";
export const DEMO_UNRECORDED_STATUS = 501;
export const DEMO_UNRECORDED_MESSAGE =
  "This view is not available in the live demo. Run GRC Lake locally to explore it.";
export const DEMO_READ_ONLY_STATUS = 405;
export const DEMO_READ_ONLY_MESSAGE =
  "The live demo is read-only. Run GRC Lake locally to make changes.";
export const DEMO_READ_ONLY_TOAST_ID = "demo-read-only";

export interface DemoManifest {
  version: 1;
  recorded_at: string;
  entries: Record<string, { status: number; file: string }>;
}

/** Path plus query with parameters sorted, so order never splits a key. */
export function snapshotKey(input: string, origin: string): string {
  const url = new URL(input, origin);
  const params = [...url.searchParams].sort(([a, av], [b, bv]) =>
    a === b ? (av < bv ? -1 : av > bv ? 1 : 0) : a < b ? -1 : 1,
  );
  const query = new URLSearchParams(params).toString();
  return query ? `${url.pathname}?${query}` : url.pathname;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

export function createDemoFetch({
  realFetch,
  origin,
  dataBase,
  onBlockedMutation,
}: {
  realFetch: typeof fetch;
  origin: string;
  dataBase: string;
  onBlockedMutation: (method: string, path: string) => void;
}): typeof fetch {
  let manifest: Promise<DemoManifest> | null = null;
  const loadManifest = () => {
    manifest ??= realFetch(`${dataBase}/manifest.json`).then((res) => {
      if (!res.ok) throw new Error(`demo manifest -> ${res.status}`);
      return res.json() as Promise<DemoManifest>;
    });
    return manifest;
  };

  return async (input, init) => {
    const request = input instanceof Request ? input : null;
    const raw = request ? request.url : String(input);
    const url = new URL(raw, origin);
    if (url.origin !== origin || !url.pathname.startsWith("/api/"))
      return realFetch(input, init);

    const method = (init?.method ?? request?.method ?? "GET").toUpperCase();
    if (method !== "GET" && method !== "HEAD") {
      onBlockedMutation(method, url.pathname);
      return json(DEMO_READ_ONLY_STATUS, {
        reason: DEMO_READ_ONLY_MESSAGE,
        errors: [{ detail: DEMO_READ_ONLY_MESSAGE }],
      });
    }

    const entry = (await loadManifest()).entries[snapshotKey(raw, origin)];
    if (!entry)
      return json(DEMO_UNRECORDED_STATUS, {
        reason: DEMO_UNRECORDED_MESSAGE,
        errors: [{ detail: DEMO_UNRECORDED_MESSAGE }],
      });
    const body = await realFetch(`${dataBase}/r/${entry.file}`);
    if (!body.ok)
      return json(DEMO_UNRECORDED_STATUS, {
        reason: DEMO_UNRECORDED_MESSAGE,
        errors: [{ detail: DEMO_UNRECORDED_MESSAGE }],
      });
    const empty = entry.status === 204 || entry.status === 304;
    return new Response(empty ? null : await body.text(), {
      status: entry.status,
      headers: { "content-type": "application/json" },
    });
  };
}
