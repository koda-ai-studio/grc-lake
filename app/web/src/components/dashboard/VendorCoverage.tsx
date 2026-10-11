"use client";

import Link from "next/link";
import { useState } from "react";
import { useVendorAssessments } from "@/lib/api/hooks";
import { QueryState } from "@/components/QueryState";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { PaginatedCollection } from "@/components/ui/paginated-collection";
import { displayLabel } from "@/lib/display";
import { formatDate } from "@/lib/format";

/** Assessment records are evidence of review, not a complete vendor inventory. */
export function VendorCoverage() {
  const assessments = useVendorAssessments();
  const [query, setQuery] = useState("");
  const rows = assessments.data ?? [];
  const vendors = new Set(
    rows.map((row) => row.vendor_name.trim().toLowerCase()),
  );
  const completed = rows.filter((row) => row.status === "completed");
  const visible = rows.filter((row) =>
    `${row.vendor_name} ${row.owner} ${row.status}`
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <QueryState queries={assessments} label="vendor assessments">
      <Card className="grid gap-5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">
              Vendor assessment coverage
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              {vendors.size} named vendors · {completed.length} completed
              assessments · {rows.length - completed.length} unfinished
              assessments. These records do not establish a complete vendor
              inventory or current certification.
            </p>
          </div>
          <Link href="/vendor-risk" className="ui-link text-sm">
            Manage vendor reviews →
          </Link>
        </div>
        {rows.length ? (
          <>
            <input
              aria-label="Search vendor assessments"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a vendor, owner or status…"
              className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
            />
            <div className="grid gap-3">
              <PaginatedCollection label="Vendor assessments">
                {visible.map((row) => (
                  <article
                    key={row.id}
                    className="grid items-center gap-3 rounded-lg border border-line p-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]"
                  >
                    <div className="min-w-0">
                      <h3 className="break-words font-semibold">
                        {row.vendor_name}
                      </h3>
                      <p className="mt-1 text-sm text-muted">
                        Owner: {row.owner || "Unassigned"} ·{" "}
                        {row.control_id || "No control linked"}
                      </p>
                    </div>
                    <div className="text-sm text-muted">
                      <p>
                        Due: {row.due_at ? formatDate(row.due_at) : "Not set"}
                      </p>
                      <p>
                        Completed:{" "}
                        {row.completed_at
                          ? formatDate(row.completed_at)
                          : "Not completed"}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Badge
                        tone={
                          row.status === "completed" ? "ready" : "attention"
                        }
                      >
                        {displayLabel(row.status)}
                      </Badge>
                      {row.risk_level && (
                        <Badge
                          tone={
                            row.risk_level === "high" ||
                            row.risk_level === "critical"
                              ? "critical"
                              : "default"
                          }
                        >
                          {displayLabel(row.risk_level)} risk
                        </Badge>
                      )}
                    </div>
                  </article>
                ))}
              </PaginatedCollection>
              {!visible.length && (
                <p className="text-sm text-muted">
                  No vendor assessments match this search.
                </p>
              )}
            </div>
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-line p-5">
            <p className="font-medium">No vendor assessments recorded</p>
            <p className="mt-2 text-sm text-muted">
              Add a named vendor, assign an owner and complete a questionnaire
              to show reviewed vendors here. Connected source providers are
              tracked separately under Sources & operations.
            </p>
          </div>
        )}
      </Card>
    </QueryState>
  );
}
