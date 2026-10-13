"use client";

import { useState } from "react";
import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import { api } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ConnectorMark } from "@/components/connectors/ConnectorMark";

export function PublicRepoAudit() {
  const [repo, setRepo] = useState("");
  const qc = useQueryClient();
  const audit = useMutation({
    mutationFn: api.auditPublicRepo,
    onSuccess: () => {
      void qc.invalidateQueries();
    },
  });
  const result = audit.data;
  return (
    <Card className="border-brand/25">
      <CardHeader className="p-5 pb-3 sm:p-6 sm:pb-3">
        <div className="flex items-center gap-3">
          <ConnectorMark connectorId="github-security" size="sm" />
          <div>
            <CardTitle className="text-lg">
              Start with a public repository
            </CardTitle>
            <p className="mt-1 text-sm text-muted">
              Paste a GitHub URL. No GitHub token needed.
            </p>
          </div>
        </div>
      </CardHeader>
      <CardContent className="grid gap-4 p-5 pt-0 sm:p-6 sm:pt-0">
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (!audit.isPending && repo.trim()) audit.mutate(repo.trim());
          }}
        >
          <div className="min-w-0 flex-1 basis-64">
            <label
              htmlFor="public-repository-url"
              className="mb-1 block text-xs font-semibold text-ink"
            >
              Public GitHub repository URL
            </label>
            <input
              id="public-repository-url"
              type="url"
              required
              maxLength={220}
              placeholder="https://github.com/owner/repository"
              value={repo}
              onChange={(event) => setRepo(event.target.value)}
              disabled={audit.isPending}
              aria-describedby="public-repository-scope"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
            />
          </div>
          <Button
            type="submit"
            variant="primary"
            disabled={audit.isPending || !repo.trim()}
          >
            {audit.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <ArrowRight className="h-4 w-4" aria-hidden />
            )}
            {audit.isPending
              ? "Collecting public evidence…"
              : "Investigate repository"}
          </Button>
        </form>
        <p
          id="public-repository-scope"
          className="text-xs leading-5 text-muted"
        >
          Public evidence only. Private governance settings remain unknown.
        </p>
        <details className="text-xs text-muted">
          <summary className="w-fit cursor-pointer">What this checks</summary>
          <p className="mt-2 max-w-2xl leading-5">
            Reads public files and ownership signals at a recorded commit, plus
            current repository metadata. Branch protection, private alerts and
            organization policies remain unknown until you connect authenticated
            access. Public observations are not proof of compliance. Repository
            code is never executed. Connector management permission is required
            to add evidence.
          </p>
        </details>
        {audit.isPending && (
          <p role="status" className="text-sm text-muted">
            Queued or collecting, then evaluating evidence. This job continues
            if you leave this page. See recent jobs for its status.
          </p>
        )}
        {audit.error && (
          <p
            role="alert"
            className="rounded-lg border border-line p-3 text-sm text-danger-fg"
          >
            {audit.error.message}
          </p>
        )}
        {result && !audit.isPending && !audit.error && (
          <div
            role="status"
            className="grid gap-2 rounded-lg border border-line bg-surfaceMuted p-3"
          >
            <p className="text-sm font-semibold text-ink">
              {result.evidence_count} observations · {result.repo}
            </p>
            <p className="break-all text-xs text-muted">
              Commit {result.source_commit} · ref {result.source_ref}
            </p>
            <p className="break-all text-xs text-muted">
              Observed {result.observed_at} · observation{" "}
              {result.observation_id}
              {result.synthetic ? " · fixture data" : ""}
            </p>
            <div className="flex flex-wrap gap-2">
              <Button asChild variant="primary" size="sm">
                <Link href={result.investigate_href}>
                  Open evidence investigation <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              <Button asChild size="sm">
                <Link href="/connectors/?connect=github-security&onboarding=1">
                  Add authenticated governance
                </Link>
              </Button>
            </div>
            <p className="text-xs text-muted">
              Authenticated collection adds governance observations with its own
              provenance. Public observations remain available.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
