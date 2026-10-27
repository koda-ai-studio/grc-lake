"use client";

import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import {
  controlResultPresentation,
  mappingCountsLabel,
  mappingReviewHref,
  type CcfResultFields,
} from "@/lib/control-attestation";
import { displayLabel } from "@/lib/display";
import { cn } from "@/lib/utils";

/** Control test result, qualified by whether the framework result attests it. */
export function ControlResultBadge({
  status,
  ccf,
  className,
}: {
  status: string;
  ccf: CcfResultFields;
  className?: string;
}) {
  const shown = controlResultPresentation(status, ccf);
  return (
    <Badge tone={shown.tone} className={className}>
      {shown.label}
    </Badge>
  );
}

/** Framework (CCF) result with its reviewed/proposed mapping counts. */
export function CcfAttestationNote({
  ccf,
  frameworkId,
  className,
}: {
  ccf: CcfResultFields;
  frameworkId?: string | null;
  className?: string;
}) {
  const status = ccf.ccf_status ?? "not_evaluated";
  return (
    <div className={cn("grid gap-1 text-xs text-muted", className)}>
      <span>
        <Badge tone={status === "pass" ? "ready" : "default"}>
          {status === "pass" ? "Attested" : displayLabel(status)}
        </Badge>{" "}
        {mappingCountsLabel(ccf)}
      </span>
      {status !== "pass" && (
        <span>
          An attested pass needs fresh evidence explicitly bound to every
          required reviewed safeguard, with passing outcomes. Mapping review
          alone cannot fill evidence gaps.{" "}
          <Link
            href={mappingReviewHref(frameworkId)}
            className="font-semibold text-brand hover:underline"
          >
            Open Mapping review →
          </Link>
        </span>
      )}
    </div>
  );
}
