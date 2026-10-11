"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../client";
import { LIVE, STALE } from "./shared";
import type {
  AccessReviewCampaign,
  AccessReviewDecision,
  AccessReviewStatus,
  ControlRemediation,
} from "../types";

export function useAccessReviews(query = "") {
  return useQuery({
    queryKey: ["access-reviews", query],
    queryFn: () => api.accessReviews(query),
    staleTime: STALE,
    refetchInterval: LIVE,
  });
}

export function useAccessReview(id: string | null) {
  return useQuery({
    queryKey: ["access-review", id],
    queryFn: () => api.accessReview(id as string),
    enabled: Boolean(id),
    staleTime: STALE,
  });
}

export function useAccessReviewItems(id: string | null, query = "") {
  return useQuery({
    queryKey: ["access-review-items", id, query],
    queryFn: () => api.accessReviewItems(id as string, query),
    enabled: Boolean(id),
    staleTime: STALE,
  });
}

export function useAccessReviewCoverage() {
  return useQuery({
    queryKey: ["access-review-coverage"],
    queryFn: () => api.accessReviewCoverage(),
    staleTime: STALE,
    refetchInterval: LIVE,
  });
}

export function useCreateAccessReviewMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { name: string } & Partial<AccessReviewCampaign>) =>
      api.createAccessReview(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["access-reviews"] }),
  });
}

export function useSetAccessReviewStatusMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; status: AccessReviewStatus }) =>
      api.setAccessReviewStatus(vars.id, vars.status),
    onSuccess: (_data, vars) => {
      qc.invalidateQueries({ queryKey: ["access-review", vars.id] });
      qc.invalidateQueries({ queryKey: ["access-reviews"] });
      qc.invalidateQueries({ queryKey: ["access-review-coverage"] });
    },
  });
}

export function useSeedAccessReviewMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.seedAccessReview(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["access-review-items", id] });
      qc.invalidateQueries({ queryKey: ["access-review", id] });
    },
  });
}

export function useDecideAccessReviewItemMutation(campaignId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      itemId: string;
      decision: AccessReviewDecision;
      note?: string;
    }) => api.decideAccessReviewItem(vars.itemId, vars.decision, vars.note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["access-review-items", campaignId] });
      qc.invalidateQueries({ queryKey: ["access-review", campaignId] });
      qc.invalidateQueries({ queryKey: ["access-review-coverage"] });
    },
  });
}

export function useControlRemediation(controlId: string | null) {
  return useQuery<ControlRemediation>({
    queryKey: ["control-remediation", controlId],
    queryFn: () => api.controlRemediation(controlId as string),
    enabled: Boolean(controlId),
    staleTime: 60_000,
  });
}

export function usePolicyTemplates() {
  return useQuery({
    queryKey: ["policy-templates"],
    queryFn: () => api.policyTemplates(),
    staleTime: STALE,
  });
}

export function useVendorQuestionnaires() {
  return useQuery({
    queryKey: ["vendor-questionnaires"],
    queryFn: () => api.vendorQuestionnaires(),
    staleTime: STALE,
  });
}

export function usePolicies(query = "") {
  return useQuery({
    queryKey: ["policies", query],
    queryFn: () => api.policies(query),
    staleTime: STALE,
    refetchInterval: LIVE,
  });
}

export function useVendorAssessments(query = "") {
  return useQuery({
    queryKey: ["vendor-assessments", query],
    queryFn: () => api.vendorAssessments(query),
    staleTime: STALE,
    refetchInterval: LIVE,
  });
}

export function usePolicy(id: string | null) {
  return useQuery({
    queryKey: ["policy", id],
    queryFn: () => api.policy(id as string),
    enabled: Boolean(id),
    staleTime: STALE,
  });
}

export function useVendorAssessment(id: string | null) {
  return useQuery({
    queryKey: ["vendor-assessment", id],
    queryFn: () => api.vendorAssessment(id as string),
    enabled: Boolean(id),
    staleTime: STALE,
  });
}

export function usePolicyCoverage() {
  return useQuery({
    queryKey: ["policy-coverage"],
    queryFn: () => api.policyCoverage(),
    staleTime: STALE,
  });
}

export function usePolicyAcknowledgments(documentId: string | null) {
  return useQuery({
    queryKey: ["policy-acknowledgments", documentId],
    queryFn: () => api.policyAcknowledgments(documentId as string),
    enabled: Boolean(documentId),
    staleTime: STALE,
  });
}

export function usePolicyAttestationSummary() {
  return useQuery({
    queryKey: ["policy-attestation-summary"],
    queryFn: () => api.policyAttestationSummary(),
    staleTime: STALE,
  });
}

export function useRecordPolicyAcknowledgmentMutation(documentId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { user_email?: string; display_name?: string }) =>
      api.recordPolicyAcknowledgment(documentId, payload),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["policy-acknowledgments", documentId],
      });
      qc.invalidateQueries({ queryKey: ["policy-attestation-summary"] });
      qc.invalidateQueries({ queryKey: ["platform", "audit-readiness"] });
    },
  });
}

export function useAdoptPolicyMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      template_id: string;
      variables?: Record<string, string>;
      owner?: string;
    }) => api.adoptPolicy(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policies"] });
      qc.invalidateQueries({ queryKey: ["policy-coverage"] });
    },
  });
}

export function useCreateVendorAssessmentMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      vendor_name: string;
      template_id: string;
      owner?: string;
      control_id?: string | null;
    }) => api.createVendorAssessment(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vendor-assessments"] }),
  });
}

export function useUpdatePolicyMutation(policyId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof api.updatePolicy>[1]) =>
      api.updatePolicy(policyId as string, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["policies"] });
      qc.invalidateQueries({ queryKey: ["policy", policyId] });
    },
  });
}

export function useUpdateVendorAssessmentMutation(assessmentId: string | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof api.updateVendorAssessment>[1]) =>
      api.updateVendorAssessment(assessmentId as string, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vendor-assessments"] });
      qc.invalidateQueries({ queryKey: ["vendor-assessment", assessmentId] });
    },
  });
}

export function usePublishPolicyMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.publishPolicy(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["policies"] });
      qc.invalidateQueries({ queryKey: ["policy", id] });
      qc.invalidateQueries({ queryKey: ["policy-coverage"] });
    },
  });
}

export function useSubmitVendorAssessmentMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.submitVendorAssessment(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ["vendor-assessments"] });
      qc.invalidateQueries({ queryKey: ["vendor-assessment", id] });
    },
  });
}
