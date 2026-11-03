import familyLabels from "../../lib/ccf-family-labels.json";
import {
  Activity,
  Bot,
  Boxes,
  Bug,
  Building2,
  CheckCheck,
  Code2,
  Database,
  FileClock,
  Fingerprint,
  GitBranch,
  HeartPulse,
  Landmark,
  Layers,
  LockKeyhole,
  Network,
  Radar,
  Scale,
  ShieldAlert,
  SlidersHorizontal,
  UserCheck,
  Users,
  Workflow,
  Wrench,
} from "lucide-react";

const FAMILY_LABELS = new Map(Object.entries(familyLabels));

const FAMILY_ICONS = {
  identity: Fingerprint,
  "data-protection": Database,
  "change-management": GitBranch,
  governance: Landmark,
  detection: Radar,
  logging: FileClock,
  "vulnerability-management": Bug,
  "third-party-risk": Users,
  "risk-management": Scale,
  availability: HeartPulse,
  "ai-governance": Bot,
  "incident-response": ShieldAlert,
  privacy: LockKeyhole,
  "controls-operations": Workflow,
  monitoring: Activity,
  "configuration-management": SlidersHorizontal,
  "secure-development": Code2,
  "secure-architecture": Boxes,
  "network-security": Network,
  "people-security": UserCheck,
  "physical-security": Building2,
  "system-maintenance": Wrench,
  "processing-integrity": CheckCheck,
};

export function controlFamily(domain: string) {
  return {
    label: FAMILY_LABELS.get(domain) ?? domain.replaceAll("-", " "),
    icon: FAMILY_ICONS[domain as keyof typeof FAMILY_ICONS] ?? Layers,
  };
}

export function ControlFamilyIcon({ domain }: { domain: string }) {
  const { icon: Icon } = controlFamily(domain);
  return (
    <span
      aria-hidden="true"
      className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-surfaceMuted text-muted"
    >
      <Icon className="h-[18px] w-[18px]" />
    </span>
  );
}
