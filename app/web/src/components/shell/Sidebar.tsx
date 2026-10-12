"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as Dialog from "@radix-ui/react-dialog";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  ChevronDown,
  PanelLeftClose,
  PanelLeftOpen,
  ChevronRight,
  X,
} from "lucide-react";
import { SidebarFooter } from "./SidebarFooter";
import { cn } from "@/lib/utils";
import { usePersistentState } from "@/lib/state/preferences";
import {
  NAV_GROUPS,
  NAV_GROUP_ICONS,
  NAV_ITEMS,
  isActiveRoute,
  type NavGroup,
} from "@/lib/nav";

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-rail";

function NavLinks({
  collapsed,
  onNavigate,
}: {
  collapsed: boolean;
  onNavigate?: () => void;
}) {
  const pathname = usePathname() ?? "/dashboard";
  const [closedGroups, setClosedGroups] = usePersistentState<
    Record<string, boolean>
  >("trustops:sidebar:closed-groups", {});

  const defaultClosed = (group: NavGroup) =>
    !NAV_ITEMS.some(
      (item) => item.group === group && isActiveRoute(pathname, item.href),
    );
  const toggleGroup = (group: NavGroup) => {
    setClosedGroups((prev) => ({
      ...prev,
      [group]: !(prev[group] ?? defaultClosed(group)),
    }));
  };

  // Keep the current page in view, and fade whichever edge has more links
  // past it so a scrolled rail never hides items without a hint.
  const navRef = useRef<HTMLElement>(null);
  const [edges, setEdges] = useState({ top: false, bottom: false });
  const measure = useCallback(() => {
    const el = navRef.current;
    if (!el) return;
    const top = el.scrollTop > 1;
    const bottom = el.scrollTop + el.clientHeight < el.scrollHeight - 1;
    setEdges((prev) =>
      prev.top === top && prev.bottom === bottom ? prev : { top, bottom },
    );
  }, []);
  useEffect(() => {
    navRef.current
      ?.querySelector<HTMLElement>('a[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest" });
    measure();
  }, [pathname, measure]);
  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [measure]);

  return (
    <div className="relative min-h-0">
      <div
        aria-hidden="true"
        data-testid="nav-fade-top"
        className={cn(
          "pointer-events-none absolute inset-x-0 top-0 z-10 h-6 bg-gradient-to-b from-rail to-transparent transition-opacity",
          edges.top ? "opacity-100" : "opacity-0",
        )}
      />
      <nav
        ref={navRef}
        aria-label="Primary"
        onScroll={measure}
        className="h-full overflow-y-auto px-2 py-1.5"
      >
        {NAV_GROUPS.map((group) => {
          const GroupIcon = NAV_GROUP_ICONS[group];
          const groupItems = NAV_ITEMS.filter((item) => item.group === group);
          if (collapsed)
            return (
              <DropdownMenu.Root key={group}>
                <DropdownMenu.Trigger asChild>
                  <button
                    type="button"
                    aria-label={group}
                    title={group}
                    aria-current={!defaultClosed(group) ? "true" : undefined}
                    className={cn(
                      "mb-1 grid h-10 w-full place-items-center rounded-md",
                      FOCUS_RING,
                      !defaultClosed(group)
                        ? "bg-rail-active text-brand"
                        : "text-rail-heading hover:bg-rail-hover hover:text-ink",
                    )}
                  >
                    <GroupIcon
                      aria-hidden="true"
                      className="h-5 w-5"
                      strokeWidth={1.75}
                    />
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    side="right"
                    align="start"
                    sideOffset={10}
                    collisionPadding={12}
                    aria-label={group}
                    className="z-[60] min-w-[220px] max-h-[var(--radix-dropdown-menu-content-available-height)] overflow-y-auto rounded-lg border border-line bg-surface p-1.5 shadow-hero"
                  >
                    <DropdownMenu.Label className="px-2 py-2 text-xs font-semibold text-muted">
                      {group}
                    </DropdownMenu.Label>
                    {groupItems.map(({ href, label, Icon }) => {
                      const active = isActiveRoute(pathname, href);
                      return (
                        <DropdownMenu.Item key={href} asChild>
                          <Link
                            href={href}
                            onClick={onNavigate}
                            aria-current={active ? "page" : undefined}
                            className={cn(
                              "flex items-center gap-2.5 rounded-md px-2 py-2 text-sm outline-none data-[highlighted]:bg-rail-hover data-[highlighted]:text-ink",
                              active ? "bg-rail-active text-brand" : "text-ink",
                            )}
                          >
                            <Icon aria-hidden="true" className="h-4 w-4" />
                            {label}
                          </Link>
                        </DropdownMenu.Item>
                      );
                    })}
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
            );
          const isClosed = closedGroups[group] ?? defaultClosed(group);
          const groupId = `nav-group-${group.replace(/\W+/g, "-").toLowerCase()}`;
          return (
            <div key={group} className="mb-1 last:mb-0">
              <button
                type="button"
                onClick={() => toggleGroup(group)}
                aria-expanded={!isClosed}
                aria-controls={groupId}
                className={cn(
                  "flex w-full items-center justify-between rounded-md px-2.5 py-2 text-[11px] font-semibold uppercase tracking-wide text-rail-heading hover:text-ink",
                  FOCUS_RING,
                )}
              >
                <span className="flex items-center gap-2.5">
                  <GroupIcon
                    aria-hidden="true"
                    className="h-4 w-4"
                    strokeWidth={1.75}
                  />
                  {group}
                </span>
                {isClosed ? (
                  <ChevronRight aria-hidden="true" className="h-3 w-3" />
                ) : (
                  <ChevronDown aria-hidden="true" className="h-3 w-3" />
                )}
              </button>
              {!isClosed && (
                <ul id={groupId} className="grid">
                  {groupItems.map(({ href, label, Icon }) => {
                    const active = isActiveRoute(pathname, href);
                    return (
                      <li key={href}>
                        <Link
                          href={href}
                          onClick={onNavigate}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex h-9 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors",
                            FOCUS_RING,
                            active
                              ? "bg-rail-active font-semibold text-brand"
                              : "text-rail-text hover:bg-rail-hover hover:text-ink",
                          )}
                        >
                          <span
                            aria-hidden="true"
                            className={cn(
                              "grid h-5 w-5 shrink-0 place-items-center",
                              active ? "text-brand" : "text-rail-heading",
                            )}
                          >
                            <Icon className="h-4 w-4" strokeWidth={1.75} />
                          </span>
                          {label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          );
        })}
      </nav>
      <div
        aria-hidden="true"
        data-testid="nav-fade-bottom"
        className={cn(
          "pointer-events-none absolute inset-x-0 bottom-0 z-10 h-8 bg-gradient-to-t from-rail to-transparent transition-opacity",
          edges.bottom ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

/** Persistent rail from `md` up; below that the TopBar opens `MobileNav`. */
export function Sidebar() {
  const [collapsed, setCollapsed] = usePersistentState(
    "trustops:sidebar:collapsed",
    false,
  );

  return (
    <aside
      aria-label="Console sidebar"
      className={cn(
        "sticky top-[var(--topbar-h)] h-[calc(100dvh-var(--topbar-h))] grid-rows-[auto_minmax(0,1fr)_auto] self-start border-r border-rail-line bg-rail text-muted transition-[width] hidden md:grid",
        collapsed ? "w-[64px]" : "w-[248px]",
      )}
    >
      <div className="flex h-11 items-center justify-between gap-2 border-b border-rail-line px-3">
        {!collapsed && (
          <span className="text-xs font-medium text-muted">Workspace</span>
        )}
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-expanded={!collapsed}
          className={cn(
            "grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted hover:bg-rail-hover hover:text-ink",
            FOCUS_RING,
          )}
        >
          {collapsed ? (
            <PanelLeftOpen aria-hidden="true" className="h-4 w-4" />
          ) : (
            <PanelLeftClose aria-hidden="true" className="h-4 w-4" />
          )}
        </button>
      </div>
      <NavLinks collapsed={collapsed} />
      <SidebarFooter collapsed={collapsed} />
    </aside>
  );
}

export function MobileNav({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // The drawer only exists below md; never leave a hidden modal trapping focus.
  useEffect(() => {
    if (!open) return;
    const query = window.matchMedia("(min-width: 768px)");
    const close = () => {
      if (query.matches) onOpenChange(false);
    };
    close();
    query.addEventListener("change", close);
    return () => query.removeEventListener("change", close);
  }, [open, onOpenChange]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm md:hidden" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 grid w-[min(288px,calc(100vw-48px))] grid-rows-[auto_1fr_auto] border-r border-rail-line bg-rail text-muted shadow-hero md:hidden">
          <div className="flex h-[var(--topbar-h)] items-center justify-between border-b border-rail-line px-4">
            <Dialog.Title className="text-sm font-semibold text-ink">
              Navigation
            </Dialog.Title>
            <Dialog.Description className="sr-only">
              Console sections
            </Dialog.Description>
            <Dialog.Close
              aria-label="Close navigation"
              className={cn(
                "grid h-8 w-8 place-items-center rounded-md text-muted hover:bg-rail-hover hover:text-ink",
                FOCUS_RING,
              )}
            >
              <X aria-hidden="true" className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <NavLinks collapsed={false} onNavigate={() => onOpenChange(false)} />
          <SidebarFooter collapsed={false} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
