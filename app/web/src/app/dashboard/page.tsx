"use client";

import {
  useControlTests,
  useFrameworks,
  useIngestionStatus,
  usePosture,
  usePostureStream,
} from "@/lib/api/hooks";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { DashboardPanel } from "@/components/dashboard/DashboardPanel";
import { AssessmentOverview } from "@/components/dashboard/AssessmentOverview";
import { ControlFamilies } from "@/components/dashboard/ControlFamilies";
import { ReadinessGrid } from "@/components/dashboard/ReadinessGrid";
import { FixNext } from "@/components/dashboard/FixNext";
import { ControlTestTable } from "@/components/dashboard/ControlTestTable";
import { IngestionStatusPanel } from "@/components/dashboard/IngestionStatusPanel";
import { EvalRunsStrip } from "@/components/dashboard/EvalRunsStrip";
import {
  DetailTabs,
  DetailTabList,
  DetailTab,
} from "@/components/ui/detail-tabs";
import { VendorCoverage } from "@/components/dashboard/VendorCoverage";
import { QueryState } from "@/components/QueryState";
import { PageHeader } from "@/components/PageHeader";
import { attestedPassCount } from "@/lib/control-attestation";
import { ROUTE_LABELS } from "@/lib/console-copy";
import { splitFrameworkPacks } from "@/lib/framework-packs";

export default function DashboardPage() {
  const posture = usePosture();
  const tests = useControlTests();
  const ingestion = useIngestionStatus();
  const registeredFrameworks = useFrameworks();
  usePostureStream();
  const data = posture.data;
  const frameworks = data?.frameworks ?? [];
  const { packs: frameworkPacks } = splitFrameworkPacks(
    registeredFrameworks.data ?? [],
  );
  const packCount = registeredFrameworks.data
    ? frameworkPacks.length
    : frameworks.length;

  return (
    <div className="page-shell grid gap-5">
      <PageHeader
        title={ROUTE_LABELS["/dashboard"]}
        description="Your evidence, coverage gaps, and next actions in one place."
      />

      <QueryState queries={[posture, ingestion]} label="overview">
        <DetailTabs defaultValue="assessment">
          <DetailTabList
            label="Overview workspace"
            items={[
              { value: "assessment", label: "Assessment" },
              { value: "sources", label: "Sources & operations" },
            ]}
          />
          <DetailTab value="assessment">
            <AssessmentOverview
              assessment={data}
              ingestion={ingestion.data}
              frameworkCount={packCount}
              catalog={registeredFrameworks.data}
              attested={tests.data ? attestedPassCount(tests.data) : undefined}
            />
            <div className="grid min-w-0 items-start gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
              <DashboardPanel
                title="Framework coverage"
                storageKey="dashboard-compliance-panel"
                tabs={[
                  {
                    label: "Frameworks",
                    content: (
                      <ReadinessGrid
                        embedded
                        frameworks={frameworks}
                        catalog={registeredFrameworks.data ?? []}
                      />
                    ),
                  },
                  {
                    label: "Control families",
                    content: <ControlFamilies embedded />,
                  },
                  {
                    label: "Test results",
                    content: (
                      <QueryState queries={tests} label="control test results">
                        <div
                          role="region"
                          aria-label="Control test results"
                          tabIndex={0}
                          className="max-h-[440px] overflow-auto"
                        >
                          <ControlTestTable rows={tests.data ?? []} />
                        </div>
                      </QueryState>
                    ),
                  },
                ]}
              />
              <CollapsibleCard
                title="Priority actions"
                storageKey="dashboard-operations-panel"
                contentClassName="p-0"
              >
                <FixNext embedded violations={data?.violations ?? []} />
                <VendorCoverage />
              </CollapsibleCard>
            </div>
          </DetailTab>
          <DetailTab value="sources">
            <IngestionStatusPanel status={ingestion.data} embedded />
            <details className="rounded-xl border border-line p-4">
              <summary className="cursor-pointer text-sm font-semibold">
                Evaluation cadence
              </summary>
              <EvalRunsStrip embedded limit={4} />
            </details>
          </DetailTab>
        </DetailTabs>
      </QueryState>
    </div>
  );
}
