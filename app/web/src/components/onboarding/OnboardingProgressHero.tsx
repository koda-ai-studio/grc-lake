"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { usePocReadiness } from "@/lib/api/hooks";
import type { PocReadinessStep } from "@/lib/api/types";

interface Props {
  progress: number;
  shareable: boolean;
  completedBlocking: number;
  blockingTotal: number;
  currentStep: PocReadinessStep | null;
  currentHref: string | null;
}

export function OnboardingProgressHero({
  progress,
  shareable,
  completedBlocking,
  blockingTotal,
  currentStep,
  currentHref,
}: Props) {
  const readiness = usePocReadiness().data;
  const fixtureDemo =
    readiness?.access.require_auth === false &&
    readiness.connectors.enabled === 0;

  return (
    <section aria-label="Workspace setup" className="border-t border-line pt-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-ink">Workspace setup</h2>
          <p className="mt-1 text-sm text-muted">
            {shareable
              ? "Ready to share"
              : `${completedBlocking} of ${blockingTotal} required steps complete`}
            {currentStep && !shareable ? ` · Next: ${currentStep.label}` : ""}
          </p>
        </div>
        {currentHref && !shareable && (
          <Button asChild size="sm">
            <Link href={currentHref}>
              Continue setup <ArrowRight className="h-4 w-4" />
            </Link>
          </Button>
        )}
      </div>
      <div
        className="mt-3 h-1 overflow-hidden rounded-full bg-surfaceMuted"
        role="progressbar"
        aria-label="Workspace setup progress"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="h-full rounded-full bg-brand"
          style={{ width: `${progress}%` }}
        />
      </div>
      {fixtureDemo && !shareable && (
        <p
          role="note"
          data-testid="onboarding-demo-note"
          className="mt-3 text-xs leading-5 text-muted"
        >
          This demo includes evidence loaded from a sample fixture. Live setup
          and browser sign-in are needed before sharing.
        </p>
      )}
    </section>
  );
}
