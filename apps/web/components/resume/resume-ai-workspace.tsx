"use client";

import { useMemo, useState } from "react";
import {
  Bot,
  Check,
  CheckCircle2,
  Eye,
  LoaderCircle,
  LockKeyhole,
  Send,
  SkipForward,
  Sparkles,
} from "lucide-react";
import { ResumeDraftEditor } from "@/components/resume/resume-draft-editor";
import { Button } from "@/components/ui/button";
import {
  apiErrorMessage,
  createResumeQuestions,
  generateProfessionalResume,
  type ApiCareerFact,
  type ApiCareerProfile,
  type ApiResumeDraft,
  type ApiResumeInterviewAnswer,
  type ApiResumeQuestionsResult,
} from "@/lib/api-client";
import { cn } from "@/lib/utils";

type ResumeAiWorkspaceProps = {
  locale: "ar" | "en";
  profile: ApiCareerProfile;
  facts: ApiCareerFact[];
};

const categories: Record<string, { ar: string; en: string }> = {
  identity: { ar: "الهوية المهنية", en: "Professional identity" },
  education: { ar: "التعليم", en: "Education" },
  experience: { ar: "الخبرة", en: "Experience" },
  project: { ar: "المشاريع", en: "Projects" },
  skill: { ar: "المهارات", en: "Skills" },
  certification: { ar: "الشهادات", en: "Certifications" },
  language: { ar: "اللغات", en: "Languages" },
  achievement: { ar: "الإنجازات", en: "Achievements" },
};

const steps = [
  { ar: "المعلومات", en: "Information" },
  { ar: "الأسئلة الذكية", en: "Smart questions" },
  { ar: "صياغة السيرة", en: "Resume writing" },
  { ar: "المعاينة والتنزيل", en: "Preview and download" },
] as const;

export function ResumeAiWorkspace({ locale, profile, facts }: ResumeAiWorkspaceProps) {
  const [targetRole, setTargetRole] = useState("");
  const [consent, setConsent] = useState(false);
  const [questionsResult, setQuestionsResult] = useState<ApiResumeQuestionsResult | null>(null);
  const [questionIndex, setQuestionIndex] = useState(0);
  const [answerText, setAnswerText] = useState("");
  const [answers, setAnswers] = useState<ApiResumeInterviewAnswer[]>([]);
  const [loadingQuestions, setLoadingQuestions] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draft, setDraft] = useState<ApiResumeDraft | null>(null);

  const coveredCategories = useMemo(
    () => Array.from(new Set(facts.map((fact) => fact.category))).filter((category) => categories[category]),
    [facts],
  );
  const currentQuestion = questionsResult?.questions[questionIndex] ?? null;
  const questionsComplete = Boolean(
    questionsResult && questionIndex >= questionsResult.questions.length,
  );
  const activeStep = draft ? 4 : generating ? 3 : questionsResult ? 2 : 1;

  async function startQuestions() {
    if (!consent) return;
    setLoadingQuestions(true);
    setError(null);
    setDraft(null);
    setAnswers([]);
    setQuestionIndex(0);
    try {
      const result = await createResumeQuestions(profile.id, {
        language: locale,
        targetRole,
        dataSharingAcknowledged: true,
      });
      setQuestionsResult(result);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setLoadingQuestions(false);
    }
  }

  function recordAnswer(skipped: boolean) {
    if (!currentQuestion || (!skipped && !answerText.trim())) return;
    setAnswers((current) => [
      ...current,
      {
        question_id: currentQuestion.id,
        category: currentQuestion.category,
        question: currentQuestion.question,
        answer: skipped ? "" : answerText.trim(),
        skipped,
      },
    ]);
    setQuestionIndex((index) => index + 1);
    setAnswerText("");
    setError(null);
  }

  async function generateDraft() {
    if (!consent) return;
    setGenerating(true);
    setError(null);
    try {
      const result = await generateProfessionalResume(profile.id, {
        language: locale,
        targetRole,
        answers,
        dataSharingAcknowledged: true,
      });
      setDraft(result);
    } catch (nextError) {
      setError(nextError);
    } finally {
      setGenerating(false);
    }
  }

  return (
    <section className="mt-8 border-t border-border pt-8" aria-labelledby="resume-ai-workspace-title">
      <header className="max-w-3xl">
        <div className="flex items-center gap-2 text-emerald">
          <Sparkles className="h-5 w-5" aria-hidden="true" />
          <span className="text-sm font-bold">{locale === "ar" ? "كاتب السيرة الذكي" : "AI resume writer"}</span>
        </div>
        <h2 id="resume-ai-workspace-title" className="mt-2 text-2xl font-bold text-ink">
          {locale === "ar" ? "من المعلومات الخام إلى سيرة جاهزة للتحميل" : "From raw information to a downloadable resume"}
        </h2>
        <p className="mt-2 text-sm leading-7 text-muted">
          {locale === "ar"
            ? "يفهم Mistral النواقص، يسألك أسئلة متابعة مناسبة، ثم يكتب الملخص والنقاط المهنية. تمنع حواجز التحقق الادعاءات غير المدعومة بالحقائق، وتبقى مراجعتك ضرورية قبل التحميل."
            : "Mistral identifies gaps, asks relevant follow-ups, then writes the summary and professional bullets. Validation guards block claims that are not supported by your facts, and your review is still required before download."}
        </p>
      </header>

      <ol className="mt-7 grid gap-3 md:grid-cols-4" aria-label={locale === "ar" ? "مراحل بناء السيرة" : "Resume-building stages"}>
        {steps.map((step, index) => {
          const number = index + 1;
          const completed = activeStep > number;
          const active = activeStep === number;
          return (
            <li key={step.en} className={cn("flex items-center gap-3 border-b-2 pb-3", completed || active ? "border-emerald" : "border-border text-muted")}>
              <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded-full border text-sm font-bold", completed ? "border-emerald bg-emerald text-white" : active ? "border-emerald text-emerald" : "border-border")}>{completed ? <Check className="h-4 w-4" aria-hidden="true" /> : number}</span>
              <strong className={cn("text-sm", completed || active ? "text-ink" : "text-muted")}>{step[locale]}</strong>
            </li>
          );
        })}
      </ol>

      {!questionsResult && !draft ? (
        <div className="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <section className="rounded-xl border border-border bg-white p-5 md:p-6">
            <div className="flex items-start gap-3">
              <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-emerald-pale text-emerald"><Bot className="h-5 w-5" aria-hidden="true" /></span>
              <div>
                <h3 className="text-lg font-bold text-ink">{locale === "ar" ? "خلّني أفهم وش ناقص قبل ما أكتب" : "Let me identify what is missing before writing"}</h3>
                <p className="mt-1 text-sm text-muted">{locale === "ar" ? "الأسئلة تتغير حسب المعلومات الموجودة عندك، وليست نموذجًا ثابتًا." : "Questions adapt to your existing information instead of following a fixed form."}</p>
              </div>
            </div>
            <label className="mt-6 block">
              <span className="field-label">{locale === "ar" ? "المسمى أو المجال المستهدف (اختياري)" : "Target role or field (optional)"}</span>
              <input className="field-control" value={targetRole} maxLength={300} placeholder={locale === "ar" ? "مثال: محلل بيانات، موارد بشرية، تطوير برمجيات" : "For example: data analyst, HR, software development"} onChange={(event) => setTargetRole(event.target.value)} />
            </label>
            <label className="mt-5 flex cursor-pointer items-start gap-3 rounded-lg border border-border p-4 text-sm">
              <input className="mt-1 h-5 w-5 shrink-0 accent-emerald" type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
              <span>
                <strong className="block text-ink">{locale === "ar" ? "موافقة على تشغيل كاتب السيرة" : "Consent to use the AI resume writer"}</strong>
                <span className="mt-1 block text-xs leading-6 text-muted">{locale === "ar" ? "تُرسل الحقائق المهنية والإجابات بعد تنقيح بيانات التواصل. البريد والهاتف اللذان تضيفهما لاحقًا للملف لا يُرسلان إلى Mistral." : "Professional facts and answers are sent after contact details are redacted. Email and phone added later to the PDF are never sent to Mistral."}</span>
              </span>
            </label>
            {error ? <p className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
            <Button type="button" size="lg" className="mt-5" disabled={!consent || loadingQuestions} onClick={() => void startQuestions()}>
              {loadingQuestions ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Sparkles className="h-5 w-5" aria-hidden="true" />}
              {loadingQuestions ? (locale === "ar" ? "جارٍ فهم السيرة…" : "Understanding your resume…") : (locale === "ar" ? "ابدأ الأسئلة الذكية" : "Start smart questions")}
            </Button>
          </section>

          <aside className="rounded-xl border border-emerald/30 bg-emerald-pale p-5">
            <h3 className="font-bold text-ink">{locale === "ar" ? "المعلومات التي وجدناها" : "What we found"}</h3>
            <ul className="mt-4 space-y-3">
              {coveredCategories.map((category) => (
                <li key={category} className="flex items-center gap-2 text-sm text-ink"><CheckCircle2 className="h-4 w-4 shrink-0 text-emerald" aria-hidden="true" />{categories[category][locale]}</li>
              ))}
            </ul>
            <p className="mt-5 flex items-start gap-2 text-xs leading-6 text-muted"><LockKeyhole className="mt-1 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" />{locale === "ar" ? `${facts.length} معلومة مهنية قابلة للمراجعة؛ لا نعرض بيانات الاتصال هنا.` : `${facts.length} reviewable professional facts; contact details are not shown here.`}</p>
          </aside>
        </div>
      ) : null}

      {questionsResult && !draft ? (
        <div className="mt-7 grid gap-6 xl:grid-cols-[minmax(0,1fr)_280px]">
          <section className="rounded-xl border border-border bg-white p-5 md:p-6">
            {currentQuestion ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-emerald"><Sparkles className="h-5 w-5" aria-hidden="true" /><h3 className="font-bold">{locale === "ar" ? "الأسئلة الذكية" : "Smart questions"}</h3></div>
                  <span className="text-sm font-semibold text-muted">{questionIndex + 1} / {questionsResult.questions.length}</span>
                </div>
                <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-100" aria-hidden="true"><div className="h-full rounded-full bg-emerald transition-all" style={{ width: `${((questionIndex + 1) / questionsResult.questions.length) * 100}%` }} /></div>
                <div className="mt-7 rounded-xl border border-emerald/20 bg-slate-50 p-5">
                  <p className="text-xs font-bold text-emerald">{categories[currentQuestion.category]?.[locale] ?? currentQuestion.category}</p>
                  <h3 className="mt-2 text-xl font-bold leading-8 text-ink">{currentQuestion.question}</h3>
                  <p className="mt-2 text-sm leading-7 text-muted">{currentQuestion.why_it_matters}</p>
                  <textarea
                    aria-label={currentQuestion.question}
                    className="field-control mt-5 min-h-40 resize-y bg-white"
                    value={answerText}
                    maxLength={4000}
                    placeholder={currentQuestion.placeholder}
                    autoFocus
                    onChange={(event) => setAnswerText(event.target.value)}
                  />
                  <div className="mt-5 flex flex-wrap items-center gap-3">
                    <Button type="button" size="lg" disabled={!answerText.trim()} onClick={() => recordAnswer(false)}><Send className="h-5 w-5" aria-hidden="true" />{locale === "ar" ? "إرسال الإجابة" : "Submit answer"}</Button>
                    <Button type="button" variant="secondary" onClick={() => recordAnswer(true)}><SkipForward className="h-4 w-4" aria-hidden="true" />{locale === "ar" ? "تخطي" : "Skip"}</Button>
                  </div>
                </div>
              </>
            ) : questionsComplete ? (
              <div className="py-7 text-center">
                <CheckCircle2 className="mx-auto h-10 w-10 text-emerald" aria-hidden="true" />
                <h3 className="mt-4 text-xl font-bold text-ink">{locale === "ar" ? "صار عندنا ما يكفي لكتابة السيرة" : "We have enough to write your resume"}</h3>
                <p className="mx-auto mt-2 max-w-xl text-sm leading-7 text-muted">{locale === "ar" ? "سيكتب Mistral ملخصًا مهنيًا ونقاطًا قوية، ويستبعد التكرار والمعلومات غير المفيدة مثل المعدل المنخفض." : "Mistral will write a professional summary and strong bullets while removing repetition and low-value details such as a low GPA."}</p>
                {error ? <p className="mx-auto mt-4 max-w-xl rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">{apiErrorMessage(error, locale)}</p> : null}
                <Button type="button" size="lg" className="mt-5" disabled={generating} onClick={() => void generateDraft()}>{generating ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Sparkles className="h-5 w-5" aria-hidden="true" />}{generating ? (locale === "ar" ? "جارٍ كتابة السيرة…" : "Writing your resume…") : (locale === "ar" ? "ولّد السيرة الاحترافية" : "Generate professional resume")}</Button>
              </div>
            ) : null}
          </section>

          <aside className="rounded-xl border border-border bg-white p-5">
            <h3 className="font-bold text-ink">{locale === "ar" ? "ما تعلمناه حتى الآن" : "What we learned"}</h3>
            <ul className="mt-4 space-y-3 text-sm">
              {coveredCategories.slice(0, 7).map((category) => <li key={category} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald" aria-hidden="true" />{categories[category][locale]}</li>)}
              {answers.filter((answer) => !answer.skipped).map((answer) => <li key={answer.question_id} className="flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-emerald" aria-hidden="true" />{categories[answer.category]?.[locale] ?? answer.category}</li>)}
            </ul>
            <p className="mt-5 border-t border-border pt-4 text-xs leading-6 text-muted">{questionsResult.provider} · {questionsResult.model}</p>
          </aside>
        </div>
      ) : null}

      {generating && !draft && !questionsComplete ? <div className="mt-7 flex min-h-48 items-center justify-center gap-3 rounded-xl border border-border text-sm text-muted" role="status"><LoaderCircle className="h-5 w-5 animate-spin text-emerald" aria-hidden="true" />{locale === "ar" ? "Mistral يكتب السيرة الآن…" : "Mistral is writing the resume…"}</div> : null}

      {draft ? (
        <ResumeDraftEditor
          locale={locale}
          profile={profile}
          draft={draft}
          onChange={setDraft}
          regenerating={generating}
          onRegenerate={generateDraft}
        />
      ) : null}

      {draft ? (
        <div className="mt-5 flex items-start gap-2 text-xs leading-6 text-muted">
          <Eye className="mt-1 h-4 w-4 shrink-0" aria-hidden="true" />
          <span>{locale === "ar" ? `استندت الصياغة إلى ${draft.fact_count} حقيقة مهنية وإجاباتك، باستخدام ${draft.provider} · ${draft.model}.` : `The draft used ${draft.fact_count} professional facts and your answers with ${draft.provider} · ${draft.model}.`}</span>
        </div>
      ) : null}
    </section>
  );
}
