"use client";

import { useEffect, useState } from "react";
import { ArrowUpRight, Eye } from "lucide-react";
import { CONSOLE_BASE_PATH } from "@/lib/base-path";
import { BRAND } from "@/lib/brand";

function recordedLabel(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

/** Persistent notice that the hosted console replays a recorded snapshot. */
export function DemoBanner() {
  const [recorded, setRecorded] = useState("");
  useEffect(() => {
    let live = true;
    fetch(`${CONSOLE_BASE_PATH}/demo-api/manifest.json`)
      .then((res) => (res.ok ? res.json() : null))
      .then((manifest: { recorded_at?: string } | null) => {
        if (live && manifest?.recorded_at)
          setRecorded(recordedLabel(manifest.recorded_at));
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  return (
    <div
      role="note"
      aria-label="Live demo notice"
      data-testid="demo-banner"
      className="flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-info/40 bg-info-bg px-4 py-1.5 text-xs text-info-fg sm:px-5 lg:px-7"
    >
      <span className="inline-flex min-w-0 items-center gap-2">
        <Eye aria-hidden="true" className="h-3.5 w-3.5 flex-none" />
        <span>
          <strong className="font-semibold">Live demo</strong> — read-only,
          synthetic sample data{recorded ? ` recorded ${recorded}` : ""}.
          Changes are disabled.
        </span>
      </span>
      <a
        href={`${BRAND.repoUrl}#quick-start`}
        className="inline-flex items-center gap-1 font-semibold underline-offset-2 hover:underline focus-visible:underline"
      >
        Run it on your own evidence
        <ArrowUpRight aria-hidden="true" className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}
