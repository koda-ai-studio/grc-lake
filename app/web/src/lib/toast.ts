import { toast } from "sonner";
import {
  DEMO_READ_ONLY_MESSAGE,
  DEMO_READ_ONLY_TOAST_ID,
} from "@/lib/demo/snapshot";

/**
 * Thin wrapper over sonner so the app has one toast seam. Components call these
 * instead of hand-rolling fixed-position banners, so toasts stack, auto-dismiss,
 * and carry success/error styling consistently.
 */
export const notify = {
  success: (message: string) => toast.success(message),
  error: (message: string) =>
    // A blocked demo write already raised this toast; replace, don't stack.
    process.env.NEXT_PUBLIC_DEMO_SNAPSHOT === "1" &&
    message.includes(DEMO_READ_ONLY_MESSAGE)
      ? toast.error(DEMO_READ_ONLY_MESSAGE, { id: DEMO_READ_ONLY_TOAST_ID })
      : toast.error(message),
  message: (message: string) => toast(message),
};

export { toast };
