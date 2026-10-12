"use client";

import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";

export const DetailTabs = Tabs.Root;
export function DetailTabList({
  items,
  label,
}: {
  items: { value: string; label: string }[];
  label: string;
}) {
  return (
    <Tabs.List
      aria-label={label}
      className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-b border-line bg-surface pb-1"
    >
      {items.map((item) => (
        <Tabs.Trigger
          key={item.value}
          value={item.value}
          className="shrink-0 border-b-2 border-transparent px-3 py-2.5 text-sm font-medium text-muted outline-none hover:text-ink focus-visible:ring-2 focus-visible:ring-brand data-[state=active]:border-brand data-[state=active]:text-ink"
        >
          {item.label}
        </Tabs.Trigger>
      ))}
    </Tabs.List>
  );
}
export function DetailTab({
  value,
  children,
  className = "",
}: {
  value: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Tabs.Content
      value={value}
      className={`grid min-w-0 gap-5 pt-5 data-[state=inactive]:hidden outline-none focus-visible:ring-2 focus-visible:ring-brand ${className}`}
    >
      {children}
    </Tabs.Content>
  );
}
