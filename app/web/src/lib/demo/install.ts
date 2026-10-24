import { toast } from "sonner";
import { CONSOLE_BASE_PATH } from "@/lib/base-path";
import {
  DEMO_MARKER,
  DEMO_READ_ONLY_MESSAGE,
  DEMO_READ_ONLY_TOAST_ID,
  createDemoFetch,
} from "@/lib/demo/snapshot";

// Everything stays inside the function: module-level classes count as side
// effects and would keep this file in the normal build.

/** Route every `/api/*` request on the page to the recorded snapshot. */
export function installDemoSnapshot(): void {
  if (typeof window === "undefined") return;
  const flagged = window as unknown as Record<string, boolean>;
  if (flagged[DEMO_MARKER]) return;
  flagged[DEMO_MARKER] = true;

  /** The live stream has no static equivalent; the demo shows recorded state. */
  class DemoEventSource extends EventTarget {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;
    readonly CONNECTING = 0;
    readonly OPEN = 1;
    readonly CLOSED = 2;
    readyState = 0;
    readonly withCredentials: boolean;
    onopen: ((event: Event) => void) | null = null;
    onmessage: ((event: MessageEvent) => void) | null = null;
    onerror: ((event: Event) => void) | null = null;
    constructor(
      readonly url: string,
      init?: EventSourceInit,
    ) {
      super();
      this.withCredentials = Boolean(init?.withCredentials);
    }
    close(): void {
      this.readyState = 2;
    }
  }

  window.fetch = createDemoFetch({
    realFetch: window.fetch.bind(window),
    origin: window.location.origin,
    dataBase: `${CONSOLE_BASE_PATH}/demo-api`,
    onBlockedMutation: () =>
      toast.error(DEMO_READ_ONLY_MESSAGE, { id: DEMO_READ_ONLY_TOAST_ID }),
  });
  window.EventSource = DemoEventSource as unknown as typeof EventSource;
}
