"use client";

import Link from "next/link";
import { Building2, ArrowRight } from "lucide-react";
import { useVendorAssessments } from "@/lib/api/hooks";
import { QueryState } from "@/components/QueryState";

/** A review queue summary, never a claim of complete vendor coverage. */
export function VendorCoverage() {
  const assessments = useVendorAssessments();
  const rows = assessments.data ?? [];
  const pending = rows.filter(
    (row) => row.status !== "completed" && row.status !== "rejected",
  );
  const overdue = pending.filter(
    (row) => row.due_at && Date.parse(row.due_at) < Date.now(),
  ).length;
  const highRisk = pending.filter(
    (row) => row.risk_level === "high" || row.risk_level === "critical",
  ).length;
  return (
    <section
      aria-label="Vendor review priorities"
      className="border-t border-line p-4"
    >
      <QueryState queries={assessments} label="vendor review priorities">
        <Link
          href="/vendor-risk"
          className="group flex items-start gap-3 rounded-md focus-visible:ring-2 focus-visible:ring-brand"
        >
          <Building2
            aria-hidden="true"
            className="mt-0.5 h-5 w-5 shrink-0 text-brand"
          />
          <div className="min-w-0 flex-1">
            <h3 className="text-sm font-semibold group-hover:text-brand">
              Vendor reviews
            </h3>
            <p className="mt-1 text-sm text-ink">
              {rows.length
                ? `${pending.length} awaiting review · ${overdue} overdue · ${highRisk} high risk`
                : "Start your first vendor assessment"}
            </p>
            <p className="mt-1 text-xs leading-5 text-muted">
              {rows.length
                ? "Assign owners, review answers, and record a decision in Vendor risk. Counts cover recorded assessments only."
                : "Record a supplier, assign its reviewer, and assess its security evidence."}
            </p>
          </div>
          <ArrowRight
            aria-hidden="true"
            className="mt-0.5 h-4 w-4 shrink-0 text-muted"
          />
        </Link>
      </QueryState>
    </section>
  );
}
