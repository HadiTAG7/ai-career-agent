import Link from "next/link";
import Image from "next/image";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/dashboard" className="inline-flex min-h-11 items-center gap-3 font-latin text-foreground" aria-label="AI Career Agent dashboard">
      <Image
        src="/brand-mark.png"
        alt=""
        aria-hidden="true"
        width={36}
        height={36}
        priority
        className="brand-mark object-contain"
        style={{ width: 36, height: 36 }}
      />
      {compact ? null : <span className="whitespace-nowrap text-base font-bold tracking-tight sm:text-lg">AI Career Agent</span>}
    </Link>
  );
}
