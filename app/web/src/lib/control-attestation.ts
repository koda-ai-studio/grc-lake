import type { CcfResultFields as CcfWireFields } from "@/lib/api/types";
import { displayLabel } from "@/lib/display";

/** Only a CCF pass through reviewed safeguard mappings is an attested pass. */
export type CcfResultFields = Partial<CcfWireFields>;

export type ControlResultTone = "ready" | "critical" | "attention";

export interface ControlResultPresentation {
  label: string;
  tone: ControlResultTone;
  attested: boolean;
}

export function controlResultPresentation(
  testStatus: string,
  ccf: CcfResultFields,
): ControlResultPresentation {
  if (testStatus === "pass") {
    return ccf.ccf_status === "pass"
      ? { label: "Passing · Attested", tone: "ready", attested: true }
      : {
          label: "Control test passing · Not attested",
          tone: "attention",
          attested: false,
        };
  }
  return {
    label: displayLabel(testStatus),
    tone: testStatus === "fail" ? "critical" : "attention",
    attested: false,
  };
}

export function mappingCountsLabel(ccf: CcfResultFields): string {
  const reviewed = ccf.reviewed_safeguard_count ?? 0;
  const proposed = ccf.proposed_safeguard_count ?? 0;
  return `${reviewed} reviewed · ${proposed} proposed mapping${proposed === 1 ? "" : "s"}`;
}

export function attestedHeadline(testPasses: number, attested: number): string {
  return `${testPasses} control test${testPasses === 1 ? "" : "s"} passing · ${attested} attested`;
}

export function mappingReviewHref(frameworkId?: string | null): string {
  return frameworkId && frameworkId !== "unknown"
    ? `/mapping-review/?framework=${encodeURIComponent(frameworkId)}`
    : "/mapping-review/";
}
