"use client";

import type { ControlTest } from "@/lib/api/types";
import { KpiTile } from "@/components/ui/KpiTile";
import { attestedPassCount } from "@/lib/control-attestation";

function countByResult(rows: ControlTest[], result: string) {
  return rows.filter((row) => row.result === result).length;
}

export function ControlMonitoringSummary({ rows }: { rows: ControlTest[] }) {
  const passed = countByResult(rows, "pass");
  const failed = countByResult(rows, "fail");
  const error = countByResult(rows, "error");
  const total = rows.length;
  const passRate = total > 0 ? Math.round((passed / total) * 100) : 0;
  const attested = attestedPassCount(rows);

  return (
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <KpiTile
        label="Tests passing"
        value={`${passRate}%`}
        detail={`${passed} of ${total} control tests · ${attested} attested`}
        tone={
          failed > 0 || error > 0 || attested < passed ? "attention" : "ready"
        }
      />
      <KpiTile
        label="Failed tests"
        value={failed}
        detail={failed > 0 ? "Assign owners and remediate" : "No failing tests"}
        tone={failed > 0 ? "critical" : "ready"}
      />
      <KpiTile
        label="Error state"
        value={error}
        detail={error > 0 ? "Connector or eval errors" : "No connector errors"}
        tone={error > 0 ? "critical" : "ready"}
      />
      <KpiTile
        label="Monitored tests"
        value={total}
        detail="Continuous control monitoring"
        tone="brand"
      />
    </div>
  );
}
