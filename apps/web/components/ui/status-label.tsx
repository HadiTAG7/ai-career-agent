import { AlertCircle, CheckCircle2, CircleHelp, MinusCircle } from "lucide-react";
import type { RequirementStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

const styles = {
  supported: "text-emerald",
  partial: "text-amber",
  unsupported: "text-danger",
  unknown: "text-muted",
};

export function StatusLabel({ status, labels, compact = false }: { status: RequirementStatus; labels: Record<RequirementStatus, string>; compact?: boolean }) {
  const Icon = status === "supported" ? CheckCircle2 : status === "partial" ? MinusCircle : status === "unsupported" ? AlertCircle : CircleHelp;
  return (
    <span className={cn("inline-flex items-center gap-1.5 font-semibold", compact ? "text-xs" : "text-sm", styles[status])}>
      <Icon aria-hidden="true" className="h-4 w-4" />
      {labels[status]}
    </span>
  );
}
