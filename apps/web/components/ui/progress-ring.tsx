import { cn } from "@/lib/utils";

export function ProgressRing({ value, size = "md", label }: { value: number; size?: "sm" | "md" | "lg"; label?: string }) {
  const dimensions = size === "sm" ? "h-16 w-16" : size === "lg" ? "h-28 w-28" : "h-24 w-24";
  return (
    <div
      aria-label={label ?? `${value}%`}
      role="img"
      className={cn("grid shrink-0 place-items-center rounded-full", dimensions)}
      style={{ background: `conic-gradient(#07845c ${value * 3.6}deg, #e8eef3 0deg)` }}
    >
      <div className="grid h-[78%] w-[78%] place-items-center rounded-full bg-white text-xl font-bold text-ink">
        {value}%
      </div>
    </div>
  );
}
