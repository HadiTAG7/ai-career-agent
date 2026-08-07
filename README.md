# AI Career Agent

> **قدّم بذكاء، لا بكثرة.** وكيل مهني ثنائي اللغة للسوق السعودي، يبني كل
> توصية وكل جملة من حقائق مهنية راجعها المستخدم ويمكن تتبعها.

AI Career Agent is an evidence-first, bilingual career assistant for early-career
digital and technology talent in Saudi Arabia. It helps a candidate maintain a
trusted career profile, assess opportunities, prepare tailored applications, and
learn from outcomes—without inventing facts or submitting applications on the
candidate's behalf.

## حالة المشروع | Project status

هذه مستودع تأسيس الـMVP وليست خدمة إنتاج مكتملة. المزوّد الحتمي المحلي
(`AI_PROVIDER=deterministic`) يجعل التطوير والاختبارات قابلة للتكرار ولا يرسل
بيانات إلى نموذج خارجي. المصادقة الإنتاجية، تخزين الملفات، ومزوّد الذكاء
الاصطناعي الحقيقي لا تُفعّل قبل مراجعات الأمن والخصوصية.

This repository is the MVP foundation, not a production-ready service. The local
deterministic provider keeps development reproducible and sends no data to an
external model. Production authentication, object storage, and any real AI
provider remain gated by security and privacy review.

## التشغيل المحلي | Local setup

### تشغيل ثابت على Windows بدون Docker

يشغّل الأمر التالي الواجهة والـAPI مع إعداد محلي آمن، ويتحقق من Node.js وPython
ويثبت الاعتماديات عند الحاجة. يستخدم هذا المسار SQLite محلية وهوية التطوير فقط؛ لا
تضع فيه بيانات مستخدمين حقيقية.

```powershell
.\dev.cmd
```

يفتح التطبيق دائمًا على <http://localhost:3000>، وتوجد أوامر الإدارة التالية:

```powershell
.\dev.cmd status
.\dev.cmd restart
.\dev.cmd stop
```

ينشئ المشغّل `apps/api/.env` و`apps/web/.env.local` بقيم تطوير آمنة عند غيابهما،
ويحفظ أرقام العمليات والسجلات في `.local/runtime`. لا يوقف أمر `stop` أي خدمة لم
يبدأها هذا المشغّل.

### Docker Compose مع PostgreSQL

المتطلبات: Docker Desktop مع Compose v2. لا تضع مفاتيح أو بيانات مستخدمين
حقيقية في البيئة المحلية.

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up --build --wait
docker compose ps
```

على macOS أو Linux استخدم `cp .env.example .env` بدل `Copy-Item`.

| الخدمة | الرابط المحلي | فحص الصحة |
|---|---|---|
| Web | <http://localhost:3000> | <http://localhost:3000/api/health> |
| API / OpenAPI | <http://localhost:8000/docs> | <http://localhost:8000/health/ready> |
| PostgreSQL | `127.0.0.1:5432` | Docker healthcheck |
| Redis / Celery | `127.0.0.1:6379` | Docker healthcheck / worker ping |

أوقف الخدمات مع الاحتفاظ بالبيانات:

```powershell
docker compose down
```

أوامر `Makefile` مجرد اختصارات لـDocker وnpm وPython، ويمكن تشغيل الأوامر
المعروضة فيه مباشرة من PowerShell إذا لم يكن `make` مثبتًا:

```text
make up       # build and start
make logs     # follow all logs
make check    # backend lint/tests + frontend lint/build
```

للتطوير اليدوي مع PostgreSQL وRedis عبر Docker، يتطلب الـAPI Python 3.12+،
وتتطلب الواجهة Node.js 22:

```powershell
docker compose up --detach postgres redis
python -m pip install -e ".\apps\api[dev]"
python -m uvicorn career_agent_api.main:app --app-dir apps/api/src --reload
npm --prefix apps/web ci
npm --prefix apps/web run dev
```

## البنية | Architecture

| المسار | المسؤولية |
|---|---|
| `apps/web` | Next.js + TypeScript + Tailwind، واجهة عربية/إنجليزية RTL/LTR |
| `apps/api` | FastAPI، عقود المجال، PostgreSQL/Alembic، وفحوص الثقة |
| `worker` | أساس Celery ومهمة health؛ نقل الاستيراد/التوليد إليه بوابة قبل الـbeta |
| `redis` | وسيط Celery ونتائج المهام؛ ليس مصدر الحقيقة |
| `postgres` | مصدر الحقيقة للملف والأدلة والوظائف والمستندات والنتائج |

اخترنا **Celery + Redis** للـMVP لأن الفريق صغير، والباك Python، والمهام
الحالية قصيرة وقابلة لإعادة المحاولة، مع حفظ حالة العمل الأساسية في
PostgreSQL. هذا أقل عبئًا تشغيليًا من Temporal الآن. نعيد تقييم Temporal إذا
ظهرت تدفقات طويلة جدًا أو انتظار بشري أو حاجة قوية إلى replay/durable
orchestration.

راجع [متطلبات المنتج واستراتيجية السوق](docs/product-requirements-market-strategy.md)،
[بنية النظام](docs/architecture.md)، [عقود المنتج](docs/product-contracts.md)،
[قصص المستخدم والتدفقات وخارطة الـMVP](docs/user-stories-workflows-roadmap.md)،
و[سياسة الخصوصية والمنصات](docs/privacy-and-platform-policy.md).

## حواجز لا تقبل التجاوز | Non-negotiable guardrails

- لا يدخل أي ادعاء مهني إلى مستند نهائي إلا إذا استند إلى حقيقة أكدها المستخدم.
- «نسبة التطابق» تغطية متطلبات مفسّرة، وليست احتمال مقابلة أو ضمان قبول.
- لا scraping، ولا ربط جلسات أو cookies، ولا mass/auto-apply.
- روابط LinkedIn وIndeed وBayt وGulfTalent بيانات مرجعية فقط؛ الخادم لا يجلبها.
- الإرسال النهائي يدوي على منصة صاحب الوظيفة.
- بيانات المستخدم لا تُستخدم لتدريب النماذج افتراضيًا.

## النشر | Deployment

- **Web:** Vercel من `apps/web`، مع ضبط `NEXT_PUBLIC_API_BASE_URL` إلى عنوان الـAPI.
- **API/worker/data:** يحتوي `render.yaml` على Render Web Service، Background
  Worker، Postgres، وKey Value داخلي بسياسة `noeviction`.
- الأسرار والقيم الخاصة بالمجال في Render معرفة بـ`sync: false` ولا توجد أسرار
  حقيقية في المستودع.
- **بوابة إلزامية:** مخطط Render مرشح staging فقط حتى يكتمل تقييم PDPL، وموقع
  المعالجة، والمورّدين الفرعيين، وآلية نقل البيانات خارج المملكة. إذا لم يُعتمد
  النقل، تُستبدل الاستضافة بمزوّد مناسب داخل المملكة قبل إدخال بيانات حقيقية.

## English quick reference

1. Copy `.env.example` to `.env` and replace the local-only database password.
2. Run `docker compose up --build --wait`.
3. Open <http://localhost:3000>; API docs are at <http://localhost:8000/docs>.
4. Keep generation deterministic locally. Never add real credentials or candidate
   data to Git.
5. Treat deployment as blocked until the privacy and cross-border-transfer gate is
   approved.

The source-policy default is deny: search, fetch, and automated submission remain
disabled unless a licensed API or explicit written permission covers the exact use.
