import { demoApplications } from "@/lib/demo-data";
import type { Application, ApplicationStage, Job } from "@/lib/types";

const APPLICATIONS_KEY = "ai-career-agent:applications:v1";
const ANALYSIS_KEY = "ai-career-agent:last-analysis:v1";
const DEMO_ONLY = !process.env.NEXT_PUBLIC_API_BASE_URL;

export function readApplications(): Application[] {
  if (!DEMO_ONLY) return [];
  if (typeof window === "undefined") return demoApplications;
  try {
    const stored = window.localStorage.getItem(APPLICATIONS_KEY);
    return stored ? (JSON.parse(stored) as Application[]) : demoApplications;
  } catch {
    return demoApplications;
  }
}

export function updateApplicationStage(id: string, stage: ApplicationStage): Application[] {
  if (!DEMO_ONLY) return [];
  const updated = readApplications().map((application) =>
    application.id === id
      ? { ...application, stage, updatedAt: new Date().toISOString().slice(0, 10) }
      : application
  );
  window.localStorage.setItem(APPLICATIONS_KEY, JSON.stringify(updated));
  return updated;
}

export function saveJobForTracking(job: Job): Application[] {
  if (!DEMO_ONLY) return [];
  const current = readApplications();
  if (current.some((application) => application.jobId === job.id)) return current;
  const next: Application[] = [
    {
      id: `local-${job.id}`,
      jobId: job.id,
      role: job.title,
      company: job.company,
      location: job.location,
      stage: "saved",
      updatedAt: new Date().toISOString().slice(0, 10),
      nextAction: { ar: "راجع الفجوات وجهّز مستنداتك", en: "Review gaps and prepare your documents" },
      documentVersion: "—",
      isDemo: job.isDemo,
    },
    ...current,
  ];
  window.localStorage.setItem(APPLICATIONS_KEY, JSON.stringify(next));
  return next;
}

export function saveLastAnalysis(job: Job) {
  if (!DEMO_ONLY) return;
  window.localStorage.setItem(ANALYSIS_KEY, JSON.stringify(job));
}

export function readLastAnalysis(): Job | null {
  if (!DEMO_ONLY) return null;
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(ANALYSIS_KEY);
    return stored ? (JSON.parse(stored) as Job) : null;
  } catch {
    return null;
  }
}

export function clearCareerAgentLocalData() {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(APPLICATIONS_KEY);
  window.localStorage.removeItem(ANALYSIS_KEY);
}
