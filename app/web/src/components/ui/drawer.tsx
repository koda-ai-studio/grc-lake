"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { AnimatePresence, motion } from "framer-motion";
import { X, Maximize2, Minimize2 } from "lucide-react";
import { type ReactNode, useState, useRef } from "react";
import { cn } from "@/lib/utils";

interface DrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: "md" | "lg";
}

export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  width = "md",
}: DrawerProps) {
  const baseWidth = width === "lg" ? 720 : 560;
  const [customWidth, setCustomWidth] = useState<number | null>(null);
  const [maximized, setMaximized] = useState(false);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  const resize = (value: number) =>
    setCustomWidth(Math.max(360, Math.min(value, window.innerWidth, 1600)));
  const currentWidth = customWidth ?? baseWidth;
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <AnimatePresence>
        {open && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay forceMount asChild>
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[2px]"
              />
            </Dialog.Overlay>
            <Dialog.Content forceMount asChild>
              <motion.aside
                ref={panelRef}
                style={{
                  width: maximized ? "100vw" : `min(${currentWidth}px, 100vw)`,
                }}
                initial={{ x: "100%" }}
                animate={{ x: 0 }}
                exit={{ x: "100%" }}
                transition={{ type: "spring", stiffness: 320, damping: 32 }}
                className={cn(
                  "fixed bottom-0 right-0 top-0 z-50 flex max-w-full flex-col border-l border-line bg-surface shadow-hero",
                  "[overflow-wrap:anywhere]",
                )}
              >
                <div
                  role="separator"
                  aria-label="Resize drawer"
                  aria-orientation="vertical"
                  aria-valuemin={360}
                  aria-valuemax={1600}
                  aria-valuenow={currentWidth}
                  tabIndex={0}
                  className="absolute inset-y-0 -left-1 z-20 hidden w-2 cursor-col-resize touch-none hover:bg-brand/30 focus-visible:bg-brand/30 focus-visible:outline-none sm:block"
                  onPointerDown={(event) => {
                    setMaximized(false);
                    drag.current = {
                      x: event.clientX,
                      width:
                        panelRef.current?.getBoundingClientRect().width ??
                        currentWidth,
                    };
                    event.currentTarget.setPointerCapture(event.pointerId);
                  }}
                  onPointerMove={(event) => {
                    if (drag.current)
                      resize(
                        drag.current.width + drag.current.x - event.clientX,
                      );
                  }}
                  onPointerUp={() => {
                    drag.current = null;
                  }}
                  onPointerCancel={() => {
                    drag.current = null;
                  }}
                  onKeyDown={(event) => {
                    if (
                      event.key === "ArrowLeft" ||
                      event.key === "ArrowRight"
                    ) {
                      event.preventDefault();
                      setMaximized(false);
                      resize(
                        currentWidth + (event.key === "ArrowLeft" ? 40 : -40),
                      );
                    }
                  }}
                />
                <header className="flex items-start justify-between gap-3 border-b border-line px-4 py-4 sm:px-5">
                  <div className="min-w-0">
                    <Dialog.Title className="text-base font-semibold leading-snug text-ink">
                      {title}
                    </Dialog.Title>
                    {description && (
                      <Dialog.Description className="mt-1 text-xs text-muted">
                        {description}
                      </Dialog.Description>
                    )}
                  </div>
                  <button
                    type="button"
                    aria-label={
                      maximized ? "Restore drawer width" : "Expand drawer"
                    }
                    onClick={() => setMaximized((value) => !value)}
                    className="ml-auto hidden h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surfaceMuted focus-visible:ring-2 focus-visible:ring-brand sm:flex"
                  >
                    {maximized ? (
                      <Minimize2 className="h-4 w-4" />
                    ) : (
                      <Maximize2 className="h-4 w-4" />
                    )}
                  </button>
                  <Dialog.Close
                    aria-label="Close"
                    className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-surfaceMuted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                  >
                    <X className="h-4 w-4" />
                  </Dialog.Close>
                </header>
                <div
                  className={cn(
                    "min-h-0 flex-1 overflow-auto px-4 py-5 sm:px-6",
                    footer && "scroll-pb-24 pb-10",
                  )}
                >
                  {children}
                </div>
                {footer && (
                  <footer className="border-t border-line px-4 py-3 sm:px-5">
                    {footer}
                  </footer>
                )}
              </motion.aside>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}
