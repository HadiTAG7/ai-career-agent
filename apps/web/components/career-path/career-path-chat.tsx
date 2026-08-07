"use client";

import Link from "next/link";
import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
import { AlertCircle, ArrowLeft, Bot, CheckCircle2, Compass, FileCheck2, FileUser, LoaderCircle, LockKeyhole, RotateCcw, Send, ServerOff, ShieldCheck, Sparkles, Trash2, UserRound } from "lucide-react";
import { PathSuggestionCard } from "@/components/career-path/path-suggestion-card";
import { Button } from "@/components/ui/button";
import { ApiHttpError, apiConfiguration, apiErrorMessage, deleteCareerPathConversation, getCareerPathWorkspace, sendCareerPathMessage } from "@/lib/api-client";
import { useLocale } from "@/lib/i18n";
import type { CareerPathWorkspace } from "@/lib/types";

type LoadState = "loading" | "success" | "error";
type FailedTurn = { content: string; clientTurnId: string };

function createClientTurnId() {
  return globalThis.crypto.randomUUID();
}

export function CareerPathChat() {
  const { locale } = useLocale();
  const [workspace, setWorkspace] = useState<CareerPathWorkspace | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [loadError, setLoadError] = useState<unknown>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [draft, setDraft] = useState("");
  const [consentAcknowledged, setConsentAcknowledged] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<unknown>(null);
  const [pendingContent, setPendingContent] = useState<string | null>(null);
  const [failedTurn, setFailedTurn] = useState<FailedTurn | null>(null);
  const [clearing, setClearing] = useState(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (!apiConfiguration.baseUrl) return;
    let active = true;
    getCareerPathWorkspace()
      .then((result) => {
        if (!active) return;
        setWorkspace(result);
        setLoadState("success");
      })
      .catch((error: unknown) => {
        if (!active) return;
        setLoadError(error);
        setLoadState("error");
      });
    return () => { active = false; };
  }, [retryKey]);

  const starterPrompts = locale === "ar"
    ? ["أحب الأرقام والتحليل", "أحب التواصل وصنع القرار", "ما زلت غير متأكد"]
    : ["I enjoy numbers and analysis", "I enjoy communication and decision-making", "I am still unsure"];
  const messages = workspace?.conversation?.messages ?? [];
  const consentMissing = Boolean(workspace?.consent_required && !consentAcknowledged);
  const canSend = Boolean(workspace?.provider_ready && draft.trim() && !sending && !consentMissing);

  function retryLoad() {
    setWorkspace(null);
    setLoadError(null);
    setLoadState("loading");
    setRetryKey((value) => value + 1);
  }

  function chooseStarterPrompt(prompt: string) {
    setDraft(prompt);
    setSendError(null);
    composerRef.current?.focus();
  }

  function discussSuggestion(title: string) {
    setDraft(locale === "ar"
      ? `أبغى نناقش مسار ${title}: ما الذي يدعمه في ملفي، وما التجربة التي تساعدني أتأكد منه؟`
      : `I want to discuss the ${title} path: what supports it in my profile, and what experiment would help me test it?`);
    setSendError(null);
    composerRef.current?.focus();
  }

  async function submitMessage() {
    if (!workspace || !canSend) return;
    const content = draft.trim();
    const clientTurnId = failedTurn?.content === content ? failedTurn.clientTurnId : createClientTurnId();
    setSending(true);
    setSendError(null);
    setPendingContent(content);
    try {
      const result = await sendCareerPathMessage({
        content,
        client_turn_id: clientTurnId,
        expected_revision: workspace.conversation?.revision ?? 0,
        data_sharing_acknowledged: workspace.consent_required ? consentAcknowledged : false,
      });
      setWorkspace(result);
      setDraft("");
      setFailedTurn(null);
      if (!result.consent_required) setConsentAcknowledged(false);
    } catch (error) {
      setSendError(error);
      setFailedTurn({ content, clientTurnId });
      if (error instanceof ApiHttpError && error.status === 409) {
        try {
          setWorkspace(await getCareerPathWorkspace());
        } catch {
          // Preserve the original conflict so the user can retry after reloading.
        }
      }
    } finally {
      setPendingContent(null);
      setSending(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage();
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submitMessage();
    }
  }

  async function clearConversation() {
    if (!workspace?.conversation) return;
    const confirmed = window.confirm(locale === "ar" ? "مسح محادثة اكتشاف المسار؟ لا يمكن التراجع عن ذلك." : "Clear your career-path conversation? This cannot be undone.");
    if (!confirmed) return;
    setClearing(true);
    setSendError(null);
    try {
      await deleteCareerPathConversation();
      setWorkspace(await getCareerPathWorkspace());
      setDraft("");
      setFailedTurn(null);
      setConsentAcknowledged(false);
    } catch (error) {
      setSendError(error);
    } finally {
      setClearing(false);
    }
  }

  const pageHeader = (
    <header>
      <h1 className="page-title">{locale === "ar" ? "اكتشف مسارًا يستحق التجربة" : "Discover a path worth exploring"}</h1>
      <p className="mt-2 max-w-3xl text-base text-muted">
        {locale === "ar"
          ? "نتعرف على اهتماماتك ونقاط قوتك وقيودك العملية، ثم نقترح مسارات لتجربها. الاقتراحات قابلة للتعديل وليست حكمًا نهائيًا."
          : "We learn about your interests, strengths, and practical constraints, then suggest paths to test. Suggestions are editable, not a final verdict."}
      </p>
    </header>
  );

  if (!apiConfiguration.baseUrl) {
    return (
      <div className="page-wrap page-enter max-w-[1040px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-amber bg-amber-pale p-6" role="alert">
          <ServerOff className="h-8 w-8 text-amber" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-bold">{locale === "ar" ? "يحتاج المستشار إلى اتصال خادم" : "The adviser needs a server connection"}</h2>
          <p className="mt-2 text-sm text-muted">{locale === "ar" ? "اربط الواجهة بخادم API أولًا. لن نعرض محادثة أو اقتراحات تجريبية بدلًا من نتيجة حقيقية." : "Connect the interface to the API server first. No demo conversation or suggestions will replace a real result."}</p>
        </section>
      </div>
    );
  }

  if (loadState === "loading") {
    return (
      <div className="page-wrap page-enter max-w-[1040px]">
        {pageHeader}
        <div className="mt-8 flex min-h-64 items-center justify-center gap-3 rounded-xl border border-border text-sm text-muted" role="status">
          <LoaderCircle className="h-5 w-5 animate-spin text-emerald" aria-hidden="true" />
          {locale === "ar" ? "جارٍ تحميل محادثة مسارك…" : "Loading your path conversation…"}
        </div>
      </div>
    );
  }

  if (loadState === "error" || !workspace) {
    const profileMissing = loadError instanceof ApiHttpError && loadError.status === 404;
    return (
      <div className="page-wrap page-enter max-w-[1040px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-danger bg-danger-pale p-6" role="alert">
          <AlertCircle className="h-8 w-8 text-danger" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-bold">{profileMissing ? (locale === "ar" ? "أنشئ ملفك الأساسي أولًا" : "Create your basic profile first") : (locale === "ar" ? "تعذر تحميل مستشار المسار" : "Could not load the path adviser")}</h2>
          <p className="mt-2 text-sm text-muted">{profileMissing ? (locale === "ar" ? "نحتاج اسمك ولغتك أولًا، وبعدها أنشئ سيرتك الذاتية أو ارفعها قبل بدء تحديد المسار." : "We need your name and language first. Then create or upload your resume before starting path discovery.") : apiErrorMessage(loadError, locale)}</p>
          {profileMissing ? (
            <Link href="/profile" className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald px-4 text-sm font-semibold text-white hover:bg-emerald-dark">{locale === "ar" ? "إنشاء الملف" : "Create profile"}<ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" /></Link>
          ) : (
            <Button variant="secondary" className="mt-4" onClick={retryLoad}><RotateCcw className="h-4 w-4" aria-hidden="true" />{locale === "ar" ? "إعادة المحاولة" : "Try again"}</Button>
          )}
        </section>
      </div>
    );
  }

  if (workspace.confirmed_fact_count === 0) {
    return (
      <div className="page-wrap page-enter max-w-[1040px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-emerald bg-emerald-pale p-6" aria-labelledby="resume-prerequisite-title">
          <FileUser className="h-8 w-8 text-emerald" aria-hidden="true" />
          <h2 id="resume-prerequisite-title" className="mt-4 text-xl font-bold">{locale === "ar" ? "ابدأ بسيرتك الذاتية أولًا" : "Start with your resume first"}</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            {locale === "ar"
              ? "ارفع سيرتك الحالية أو أنشئ واحدة بمساعدة الذكاء الاصطناعي، ثم راجع المعلومات المستخرجة. سيستخدمها المستشار بعد تأكيدك لها لاقتراح مسارات أدق."
              : "Upload your current resume or create one with AI, then review the extracted information. Once confirmed, the adviser will use it to suggest more relevant paths."}
          </p>
          <Link href="/resume" className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-emerald px-4 text-sm font-semibold text-white hover:bg-emerald-dark">
            {locale === "ar" ? "إنشاء أو رفع السيرة" : "Create or upload resume"}
            <ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" />
          </Link>
        </section>
      </div>
    );
  }

  if (!workspace.provider_ready && !workspace.conversation) {
    return (
      <div className="page-wrap page-enter max-w-[1040px]">
        {pageHeader}
        <section className="mt-8 rounded-xl border border-amber bg-amber-pale p-6" role="alert">
          <ServerOff className="h-8 w-8 text-amber" aria-hidden="true" />
          <h2 className="mt-4 text-xl font-bold">{locale === "ar" ? "المستشار الذكي غير مفعّل على الخادم" : "The AI adviser is not enabled on the server"}</h2>
          <p className="mt-2 max-w-2xl text-sm text-muted">{locale === "ar" ? "أكمل إعداد مزود الذكاء الاصطناعي داخل بيئة خادم API ثم أعد تشغيله. حفاظًا على الأمان، لا يوجد حقل لإدخال المفتاح أو تخزينه في المتصفح." : "Configure the AI provider in the API server environment, then restart it. For security, the interface has no field for entering or storing a key."}</p>
          <p className="mt-4 text-xs text-muted">{locale === "ar" ? "لن نعرض اقتراحات وهمية أثناء عدم جاهزية المزود." : "No fake suggestions will be shown while the provider is unavailable."}</p>
        </section>
      </div>
    );
  }

  return (
    <div className="page-wrap page-enter max-w-[1180px]">
      <div className="flex flex-col gap-5 md:flex-row md:items-start md:justify-between">
        {pageHeader}
        {workspace.conversation ? (
          <Button variant="ghost" className="shrink-0 text-danger hover:bg-danger-pale" disabled={clearing} onClick={() => { void clearConversation(); }}>
            {clearing ? <LoaderCircle className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}
            {locale === "ar" ? "مسح المحادثة" : "Clear conversation"}
          </Button>
        ) : null}
      </div>

      {!workspace.provider_ready ? (
        <section className="mt-6 rounded-xl border border-amber bg-amber-pale p-4" role="alert">
          <div className="flex items-start gap-3">
            <ServerOff className="mt-0.5 h-5 w-5 shrink-0 text-amber" aria-hidden="true" />
            <div>
              <h2 className="font-bold">{locale === "ar" ? "المستشار الذكي متوقف مؤقتًا" : "The AI adviser is temporarily unavailable"}</h2>
              <p className="mt-1 text-sm text-muted">{locale === "ar" ? "يمكنك قراءة محادثتك السابقة أو مسحها، لكن إرسال رسالة جديدة متوقف حتى يُعاد تفعيل المزود على الخادم." : "You can still read or clear your previous conversation, but new messages are disabled until the server provider is enabled again."}</p>
            </div>
          </div>
        </section>
      ) : null}

      <div className="mt-8 grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
        <section className="min-w-0 rounded-xl border border-border bg-white" aria-labelledby="career-path-chat-title">
          <div className="flex items-center gap-3 border-b border-border px-5 py-4">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-emerald-pale text-emerald"><Sparkles className="h-5 w-5" aria-hidden="true" /></span>
            <div>
              <h2 id="career-path-chat-title" className="font-bold">{locale === "ar" ? "المستشار الذكي" : "AI career adviser"}</h2>
              <p className="text-xs text-muted">{locale === "ar" ? "يساعدك على الاستكشاف، ولا يقرر بدلًا منك." : "Helps you explore; it does not decide for you."}</p>
            </div>
          </div>

          <div className="space-y-5 p-5" aria-live="polite">
            {messages.length === 0 ? (
              <div className="rounded-xl bg-slate-50 p-5">
                <div className="flex items-start gap-3">
                  <Bot className="mt-1 h-5 w-5 shrink-0 text-emerald" aria-hidden="true" />
                  <div>
                    <p className="font-semibold">{locale === "ar" ? "خلّنا نبدأ بما يهمك في يوم العمل." : "Let’s start with what matters to you in a workday."}</p>
                    <p className="mt-2 text-sm text-muted">{locale === "ar" ? "اكتب بطريقتك، أو اختر بداية سريعة. سنفرّق دائمًا بين ما تقوله في المحادثة والحقائق المؤكدة في ملفك." : "Write in your own words or choose a quick start. We will always distinguish chat statements from confirmed profile facts."}</p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2" aria-label={locale === "ar" ? "بدايات مقترحة" : "Suggested starters"}>
                  {starterPrompts.map((prompt) => <button className="min-h-11 rounded-lg border border-emerald bg-white px-4 text-sm font-semibold text-emerald hover:bg-emerald-pale" type="button" key={prompt} onClick={() => chooseStarterPrompt(prompt)}>{prompt}</button>)}
                </div>
              </div>
            ) : null}

            {messages.map((message) => (
              <article className="space-y-4" key={message.id}>
                <div className={message.role === "user" ? "ms-auto max-w-[88%] rounded-xl bg-ink px-4 py-3 text-white" : "max-w-[92%] rounded-xl bg-slate-50 px-4 py-3 text-ink"}>
                  <p className={message.role === "user" ? "mb-1 flex items-center gap-2 text-xs font-bold text-white/75" : "mb-1 flex items-center gap-2 text-xs font-bold text-emerald"}>
                    {message.role === "user" ? <UserRound className="h-4 w-4" aria-hidden="true" /> : <Bot className="h-4 w-4" aria-hidden="true" />}
                    {message.role === "user" ? (locale === "ar" ? "أنت" : "You") : (locale === "ar" ? "المستشار" : "Adviser")}
                  </p>
                  <p className="whitespace-pre-wrap text-sm">{message.content}</p>
                </div>
                {message.suggestions.length > 0 ? (
                  <section className="space-y-4" aria-label={locale === "ar" ? "مسارات مقترحة" : "Suggested paths"}>
                    <div>
                      <h3 className="text-lg font-bold">{locale === "ar" ? "مسارات تستحق الاستكشاف" : "Paths worth exploring"}</h3>
                      <p className="mt-1 text-sm text-muted">{locale === "ar" ? "قارن الأسباب والنقاط المجهولة، ثم اختبر قبل أن تعتمد قرارك." : "Compare the reasoning and unknowns, then test before deciding."}</p>
                    </div>
                    {message.suggestions.map((suggestion) => <PathSuggestionCard key={`${message.id}-${suggestion.title}`} suggestion={suggestion} onDiscuss={discussSuggestion} />)}
                  </section>
                ) : null}
              </article>
            ))}

            {pendingContent ? (
              <>
                <div className="ms-auto max-w-[88%] rounded-xl bg-ink px-4 py-3 text-sm text-white"><p className="mb-1 text-xs font-bold text-white/75">{locale === "ar" ? "أنت" : "You"}</p><p>{pendingContent}</p></div>
                <div className="flex max-w-[92%] items-center gap-3 rounded-xl bg-slate-50 px-4 py-3 text-sm text-muted" role="status"><LoaderCircle className="h-4 w-4 animate-spin text-emerald" aria-hidden="true" />{locale === "ar" ? "يفكر المستشار في سؤالك…" : "The adviser is considering your message…"}</div>
              </>
            ) : null}
          </div>

          <form className="border-t border-border p-5" onSubmit={handleSubmit} aria-busy={sending}>
            <label className="field-label" htmlFor="career-path-message">{locale === "ar" ? "رسالتك" : "Your message"}</label>
            <textarea
              ref={composerRef}
              id="career-path-message"
              className="field-control min-h-28 resize-y py-3"
              value={draft}
              maxLength={3000}
              disabled={sending || !workspace.provider_ready}
              onChange={(event) => { setDraft(event.target.value); setSendError(null); }}
              onKeyDown={handleComposerKeyDown}
              placeholder={locale === "ar" ? "مثال: أحب التحليل، لكني لا أعرف هل يناسبني العمل المالي أو التقني…" : "Example: I enjoy analysis, but I am unsure whether finance or technology fits me better…"}
            />
            <div className="mt-2 flex items-center justify-between gap-3 text-xs text-muted"><span>{locale === "ar" ? "Enter للإرسال · Shift + Enter لسطر جديد" : "Enter to send · Shift + Enter for a new line"}</span><span>{draft.length}/3000</span></div>

            {workspace.consent_required ? (
              <label className="mt-4 flex cursor-pointer items-start gap-3 rounded-lg border border-border p-3 text-sm">
                <input className="mt-1 h-5 w-5 shrink-0 accent-emerald" type="checkbox" checked={consentAcknowledged} onChange={(event) => setConsentAcknowledged(event.target.checked)} />
                <span><strong className="block">{locale === "ar" ? "موافقة مشاركة البيانات" : "Data-sharing consent"}</strong><span className="mt-1 block text-xs text-muted">{locale === "ar" ? `أوافق على إرسال رسالتي وحقائق ملفي المؤكدة إلى مزود ${workspace.provider} لإنشاء الرد.` : `I agree to send my message and confirmed profile facts to ${workspace.provider} to generate the response.`}</span></span>
              </label>
            ) : null}
            {workspace.consent_required ? (
              <p className="mt-2 text-xs text-muted">
                {locale === "ar"
                  ? "يُرسل الطلب دون حفظ حالة المحادثة لدى المزود، لكن قد يحتفظ المزود بسجلات منع إساءة الاستخدام وفق إعدادات حسابه. يمكنك تصدير السجل المحلي أو حذفه من الإعدادات."
                  : "The request is sent without provider-side conversation state, though the provider may retain abuse-prevention logs under its account settings. You can export or delete the local transcript from Settings."}
              </p>
            ) : null}

            {sendError ? (
              <div className="mt-4 rounded-lg border border-danger bg-danger-pale p-3 text-sm text-danger" role="alert">
                <p>{apiErrorMessage(sendError, locale)}</p>
                <p className="mt-1 text-xs">{locale === "ar" ? "احتفظنا برسالتك؛ يمكنك إعادة الإرسال دون كتابتها من جديد." : "Your message is preserved so you can retry without retyping it."}</p>
              </div>
            ) : null}

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="space-y-1 text-xs text-muted">
                <p className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 shrink-0" aria-hidden="true" />{locale === "ar" ? "لا تشارك رقم الهوية أو بيانات بنكية أو كلمات مرور أو معلومات صحية." : "Do not share national IDs, bank details, passwords, or health information."}</p>
                <p>{locale === "ar" ? "اقتراحات المستشار لا تغيّر حقائق ملفك تلقائيًا." : "Adviser suggestions never change your profile facts automatically."}</p>
              </div>
              <Button type="submit" size="lg" disabled={!canSend}>
                {sending ? <LoaderCircle className="h-5 w-5 animate-spin" aria-hidden="true" /> : <Send className="h-5 w-5" aria-hidden="true" />}
                {sending ? (locale === "ar" ? "جارٍ الإرسال…" : "Sending…") : (locale === "ar" ? "إرسال" : "Send")}
              </Button>
            </div>
          </form>
        </section>

        <aside className="space-y-5" aria-labelledby="adviser-context-title">
          <section className="rounded-xl border border-border p-5">
            <h2 id="adviser-context-title" className="section-title">{locale === "ar" ? "ما يعرفه المستشار" : "What the adviser knows"}</h2>
            <div className="mt-5 flex items-center gap-3 rounded-lg bg-emerald-pale p-4">
              <FileCheck2 className="h-6 w-6 shrink-0 text-emerald" aria-hidden="true" />
              <div><strong className="block text-2xl">{workspace.confirmed_fact_count}</strong><span className="text-xs text-muted">{locale === "ar" ? "حقائق مؤكدة في ملفك" : "confirmed profile facts"}</span></div>
            </div>
            <p className="mt-4 text-sm text-muted">{locale === "ar" ? "نفرّق في كل اقتراح بين حقيقة راجعتها أنت ومعلومة قلتها داخل المحادثة." : "Every suggestion distinguishes facts you reviewed from statements you made in the chat."}</p>
            <Link href="/profile" className="subtle-link mt-3">{locale === "ar" ? "راجع حقائق ملفك" : "Review profile facts"}<ArrowLeft className="h-4 w-4 rtl:rotate-0 ltr:rotate-180" aria-hidden="true" /></Link>
          </section>

          <section className="rounded-xl border border-border p-5" aria-labelledby="adviser-boundaries-title">
            <ShieldCheck className="h-6 w-6 text-emerald" aria-hidden="true" />
            <h2 id="adviser-boundaries-title" className="mt-3 font-bold">{locale === "ar" ? "حدود واضحة" : "Clear boundaries"}</h2>
            <ul className="mt-3 space-y-3 text-sm text-muted">
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "لا نعرض نسبة ملاءمة أو ضمانًا وظيفيًا." : "No fit percentage or employment guarantee."}</span></li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "يمكنك تعديل رأيك أو مسح المحادثة." : "You can change your mind or clear the conversation."}</span></li>
              <li className="flex gap-2"><CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald" aria-hidden="true" /><span>{locale === "ar" ? "اختبر المسار عمليًا قبل اعتماده." : "Test a path in practice before committing."}</span></li>
            </ul>
          </section>

          <p className="flex items-center gap-2 px-1 text-xs text-muted"><Compass className="h-4 w-4" aria-hidden="true" />{workspace.model ? `${workspace.provider} · ${workspace.model}` : workspace.provider}</p>
        </aside>
      </div>
    </div>
  );
}
