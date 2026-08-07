import Link from "next/link";
import Image from "next/image";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/dashboard" className="inline-flex min-h-11 items-center gap-3 rounded-lg font-latin text-ink" aria-label="AI Career Agent dashboard">
      <Image src="/brand-mark.png" alt="" aria-hidden="true" width={36} height={36} priority className="h-9 w-9 object-contain" />
      {compact ? null : <span className="whitespace-nowrap text-lg font-bold tracking-tight">AI Career Agent</span>}
    </Link>
  );
}
