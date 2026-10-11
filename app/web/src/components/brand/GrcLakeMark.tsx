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

const LAKE_TRACE =
  "M19 13C29 9 33 20 42 22C53 25 55 36 47 44C38 53 18 54 13 44C8 33 19 29 15 22C12 17 14 14 19 13ZM24 23C28 23 31 30 38 30C45 30 44 38 37 42C30 46 20 44 21 38C22 32 26 29 24 23Z";

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
        A lake contour with connected points representing collected evidence and
        traceable records.
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
          <path d={LAKE_TRACE} strokeWidth={simple ? "4" : "3.5"} />
          <circle cx="19" cy="13" r="3.5" fill="#75b6ff" stroke="none" />
          <circle cx="47" cy="44" r="3.5" fill="#42dfcf" stroke="none" />
        </g>
      </g>
    </svg>
  );
}
