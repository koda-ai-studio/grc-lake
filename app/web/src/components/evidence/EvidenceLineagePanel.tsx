"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { displayLabel } from "@/lib/display";

/** On-demand: verification reads generation artifacts, so opening a drawer is cheap. */
export function EvidenceLineagePanel({ eventId }: { eventId: string }) {
  const [started, setStarted] = useState(false);
  const [page, setPage] = useState({
    offset: 0,
    generation: undefined as string | undefined,
  });
  const trace = useQuery({
    queryKey: ["evidence-lineage", eventId, page.offset, page.generation],
    queryFn: () => api.evidenceLineage(eventId, page.offset, page.generation),
    enabled: started,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const result = started ? trace.data?.data : undefined;
  const changePage = (offset: number) => {
    if (result)
      setPage({ offset, generation: result.generation.generation_id });
  };
  return (
    <section
      aria-label="Frozen evidence lineage"
      className="grid gap-3 rounded-xl border border-line p-3 text-sm"
    >
      <div>
        <h3 className="font-semibold">Source to frozen result</h3>
        <p className="mt-1 text-xs text-muted">
          Inspect the source identity and assessment links for this exact
          record.
        </p>
      </div>
      {!started && (
        <Button onClick={() => setStarted(true)}>Trace frozen results</Button>
      )}
      {started && trace.isFetching && (
        <p role="status">Verifying generation and source linkage…</p>
      )}
      {started && trace.isError && (
        <div role="alert" className="grid gap-2">
          <p>
            Lineage could not be verified. The assessment may have changed or
            access may be unavailable.
          </p>
          <Button
            onClick={() => {
              if (page.offset || page.generation)
                setPage({ offset: 0, generation: undefined });
              else void trace.refetch();
            }}
          >
            Reload trace
          </Button>
        </div>
      )}
      {result && !trace.isError && !trace.isFetching && (
        <>
          <p className="font-semibold">
            {result.integrity.verified
              ? "Generation integrity verified"
              : "Generation integrity unverified"}
          </p>
          <p className="text-xs text-muted">
            Hash linkage does not establish source authenticity, sufficient
            evidence, or a passing control.
          </p>
          <dl className="grid grid-cols-[100px_minmax(0,1fr)] gap-2 text-xs [&_dd]:break-all">
            <dt className="text-muted">Source account</dt>
            <dd>{result.source.source_account_id}</dd>
            <dt className="text-muted">Source event</dt>
            <dd>{result.source.source_event_id}</dd>
            <dt className="text-muted">Connector</dt>
            <dd>{result.source.connector_id ?? "Not recorded"}</dd>
            <dt className="text-muted">Generation</dt>
            <dd>{result.generation.generation_id}</dd>
          </dl>
          <details className="text-xs text-muted">
            <summary className="cursor-pointer">
              How to read these links
            </summary>
            <p className="mt-2">
              Declared controls show source associations. Safeguard links match
              this record to an aggregate frozen result.
            </p>
          </details>
          <ul className="grid gap-2">
            {result.links.map((link, index) => (
              <li
                key={`${link.kind}-${link.control_id ?? link.safeguard_id}-${index}`}
                className="rounded-lg bg-surfaceMuted p-2 text-xs"
              >
                <div>
                  {link.kind === "declared_control"
                    ? "Declared control"
                    : "Safeguard result"}
                </div>
                <div className="mt-1 break-all font-semibold">
                  {link.control_id ?? link.safeguard_id} ·{" "}
                  {displayLabel(link.result)}
                </div>
              </li>
            ))}
          </ul>
          {!result.links.length && <p>No frozen result links in this page.</p>}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span>{trace.data!.meta.count} result links</span>
            <Button
              disabled={page.offset === 0}
              onClick={() => changePage(Math.max(0, page.offset - 5))}
            >
              Previous links
            </Button>
            <Button
              disabled={
                page.offset + result.links.length >= trace.data!.meta.count
              }
              onClick={() => changePage(page.offset + 5)}
            >
              Next links
            </Button>
          </div>
        </>
      )}
    </section>
  );
}
