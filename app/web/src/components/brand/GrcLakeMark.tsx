import { cn } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

const SIZES = {
  xs: "h-5 w-5 rounded-[5px]",
  sm: "h-6 w-6 rounded-md",
  md: "h-8 w-8 rounded-lg",
  lg: "h-10 w-10 rounded-xl",
  xl: "h-12 w-12 rounded-xl",
} as const;

type Size = keyof typeof SIZES;

const EVIDENCE_LAYERS =
  "M32 14 51 24 32 34 13 24ZM13 33 32 43 51 33M13 42 32 52 51 42";

/** Keep the same silhouette at every size; small marks use a heavier stroke. */
const SIMPLE_SIZES: ReadonlySet<Size> = new Set(["xs", "sm", "md", "lg"]);

interface Props {
  size?: Size;
  className?: string;
  gradientId?: string;
  /** `auto` uses a heavier stroke at 40px and below. */
  variant?: "auto" | "full" | "simple";
}

export function GrcLakeMark({
  size = "md",
  className,
  gradientId = "grc-lake-mark-gradient",
  variant = "auto",
}: Props) {
  const simple =
    variant === "simple" || (variant === "auto" && SIMPLE_SIZES.has(size));
  return (
    <svg
      viewBox="0 0 64 64"
      role="img"
      aria-label={BRAND.name}
      data-variant={simple ? "simple" : "full"}
      className={cn("flex-none", SIZES[size], className)}
    >
      <title>{BRAND.name}</title>
      <desc>
        Three aligned layers representing collected evidence and traceable
        records.
      </desc>
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1="13"
          y1="14"
          x2="51"
          y2="52"
        >
          <stop stopColor="#4f7cff" />
          <stop offset="1" stopColor="#42dfcf" />
        </linearGradient>
      </defs>
      <g>
        <rect width="64" height="64" rx="15" fill="#0b1b2c" />
        <g
          fill="none"
          stroke={`url(#${gradientId})`}
          color="#5b9aff"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d={EVIDENCE_LAYERS} strokeWidth={simple ? "4" : "3.5"} />
        </g>
      </g>
    </svg>
  );
}
