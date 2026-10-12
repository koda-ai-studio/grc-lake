"use client";

import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/PageHeader";
import { AiGovernanceWorkspace } from "@/components/audit-room/AiGovernanceWorkspace";
import { usePlatformStream } from "@/lib/api/hooks";
import { ROUTE_LABELS } from "@/lib/console-copy";

export default function AiGovernancePage() {
  const { connected } = usePlatformStream();
  return (
    <div className="page-shell grid gap-6">
      <PageHeader
        title={ROUTE_LABELS["/ai-governance"]}
        description="See what is documented, trace model evidence, and close gaps in your AI controls."
        actions={
          <Badge tone={connected ? "ready" : "attention"}>
            {connected ? "live stream" : "polling"}
          </Badge>
        }
      />
      <AiGovernanceWorkspace />
    </div>
  );
}
