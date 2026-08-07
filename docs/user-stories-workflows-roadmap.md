# قصص المستخدم والتدفقات وخارطة الـMVP

الحالة: 2026-08-06. هذه الوثيقة تحول متطلبات المنتج إلى مسار تنفيذ 12–16
أسبوعًا من الـfoundation الحالي إلى beta مغلقة. **لا يعني وصف «منفذ» أنه جاهز
للإنتاج**؛ بوابة الأمن وPDPL ونقل البيانات تظل إلزامية.

## 1. هدف الإصدار

يستطيع باحث عمل مبكر المسيرة في السعودية أن يبني ملفًا مهنيًا موثقًا، ويحلل
وظيفة أدخلها بنفسه، ويفهم التغطية والفجوات، وينشئ حزمة تقديم لا تحتوي ادعاءات
غير مدعومة، ثم يسجل التقديم اليدوي ونتيجته. العربية والإنجليزية مساران أصليان،
ولا يوجد scraping أو auto-apply.

المقياس الشمالي بعد beta هو المقابلات البشرية المؤهلة لكل طلب أكد المستخدم
إرساله. عدد الطلبات ليس هدفًا.

### مفاتيح الحالة

- **Foundation:** عقد backend أو بنية تحتية منفذة ومختبرة للتطوير/staging.
- **Partial:** جزء حقيقي يعمل، لكن التدفق الكامل أو حماية الإنتاج ناقصة.
- **Demo:** واجهة مصطنعة أو `localStorage` لتقييم التجربة، وليست سجل المنتج.
- **Planned:** غير منفذ بعد.

## 2. الحقيقة الحالية

| القدرة | الحالة | الموجود الآن | المطلوب قبل beta/production |
|---|---|---|---|
| التشغيل | Foundation | FastAPI/Next/Postgres/Redis/Celery، migrations، Compose وCI وRender candidate | smoke على بيئة فعلية، monitoring وrunbooks |
| المصادقة والملكية | Partial | Clerk JWT في الإنتاج، owner scoping، وحارس واجهة اختياري | إعداد tenant، اختبارات E2E، rate limits وإدارة جلسات/أخطاء مكتملة |
| الملف والأدلة | Foundation/Partial | ملف واحد وواجهة متصلة للمصادر والإضافة والتأكيد والتصحيح وسحب التأكيد، مع provenance وإبطال المشتقات وحراس revision/CAS | `AuditEvent` عام، completeness أدق، واختبار تزامن PostgreSQL فعلي |
| استيراد الملف | Foundation | PDF/DOCX وLinkedIn ZIP، حدود أمان، لا يحتفظ بالخام، وكل الناتج `extracted` | malware scanning، تحسين extraction العربي، UX تصحيح/رفض |
| إدخال الوظيفة والتحليل | Foundation | وصف يدوي، URL كـmetadata، تحليل حتمي، إضافة/تصحيح/سحب واعتماد requirements، وقرار fail-closed قبل الاعتماد | ontology سعودي أوسع، calibration واختبارات جودة corpus |
| قائمة الفرص واللوحة | Partial | الوضع المتصل يفشل بأمان ويعرض حالة فارغة بدل بيانات demo؛ صفحات العرض التجريبي موسومة | ربط `/jobs` و`/dashboard` ببيانات API الحقيقية |
| المستندات | Foundation API + Demo UI | `ClaimEvidence`، فحص ذري، وFSM مراجعة/hash؛ صفحة demo معزولة وغير قابلة للاستخدام في API mode | مولد فعلي، diff، UX مراجعة، وتصدير ATS إلى PDF/DOCX |
| التقديمات والنتائج | Foundation API + Partial UI | Tracker متصل بالـAPI؛ `localStorage` محصور في demo، والمراحل التي تتطلب CV مراجع معطلة بأمان | ربط تسجيل النتائج والمتابعات، وإكمال انتقالات المستندات |
| الخصوصية | Foundation/Partial | `/me/export` و`/me/data` و`DeletionReceipt`؛ إعدادات واجهة متصلة | حذف object storage/backups، DSR workflow وSLA معتمد |
| التدقيق | Planned | timestamps متفرقة و`DeletionReceipt` فقط | `AuditEvent` عام قبل الإنتاج لكل التغييرات الحساسة |
| المهام الخلفية | Foundation infra | Celery/Redis وhealth task فقط | نقل import/generation/export/delete المكلف إلى مهام idempotent |
| البحث المدمج | Planned | لا feed ولا fetch للروابط | feed/API مرخص؛ يبقى الإدخال اليدوي fallback كاملًا |
| الذكاء الاصطناعي الخارجي | Planned | provider حتمي فقط | تقييم الخصوصية/النقل، DPA، اختبارات hallucination وkill switch |

الـdemo يجب أن يبقى موسومًا بوضوح. في beta المتصلة لا يجوز استبدال خطأ API
بفرصة أو مستند تجريبي وكأنه نتيجة حقيقية؛ يظهر الخطأ ويحافظ النظام على آخر حالة
حقيقية معروفة.

## 3. قصص المستخدم ذات الأولوية

| ID | قصة المستخدم ومعيار القبول | الأولوية | الحالة |
|---|---|---:|---|
| US-01 | كباحث عمل، أريد مساحة عربية/إنجليزية محمية؛ يتبدل RTL/LTR وتُستمد الملكية من JWT. | P0 | Partial |
| US-02 | أريد إنشاء ملف للتعليم والخبرة والمهارات والمشاريع واللغات والشهادات؛ لا تستخدم حقيقة قبل تأكيدي. | P0 | Foundation |
| US-03 | أريد استيراد CV أو LinkedIn export؛ أرى المصدر والثقة وكل الناتج يحتاج مراجعة، ولا تُستورد بيانات الآخرين. | P0 | Foundation |
| US-04 | أريد تأكيد أو تصحيح أو رفض حقيقة؛ أي تعديل يعيدها غير مؤكدة ويعيد فحص المستندات المتأثرة. | P0 | Foundation/Partial؛ التدفق وحراس CAS منفذة، ويبقى سجل التدقيق واختبار PostgreSQL |
| US-05 | أريد لصق وصف وظيفة ورابطها؛ يحفظ الرابط فقط ولا يجلب الخادم الصفحة. | P0 | Foundation |
| US-06 | أريد رؤية كل requirement كإلزامي/مفضل و`matched/missing/unknown` مع الدليل، ثم قرار مفهوم وجاهزية غير رقمية. | P0 | Foundation/Partial؛ API وواجهة القرار متصلان |
| US-07 | أريد CV ورسالة مخصصين؛ كل claim واقعي قابل للتتبع، وأراجع diff قبل تنزيل PDF/DOCX. | P0 | validator Foundation؛ generation/export Planned |
| US-08 | أريد نقل الطلب يدويًا بين الحالات وربطه بالوظيفة ونسخ المستندات؛ `submitted` يتطلب تأكيدًا مني. | P0 | Foundation/Partial؛ Tracker متصل، والمراحل المعتمدة على CV محجوبة حتى اكتمال الحزمة |
| US-09 | أريد تسجيل مقابلة/رفض/عرض ورؤية القمع والمتابعات؛ لا يستنتج النظام النتيجة من البريد. | P0 | API Foundation؛ واجهة النتائج والقمع ما زالت Planned |
| US-10 | أريد تصدير بياناتي وحذفها؛ لا أرى بيانات مستخدم آخر وأحصل على إيصال حذف بلا معرف شخصي. | P0 | Foundation/Partial |
| US-11 | أريد البحث في فرص سعودية حديثة؛ يظهر المصدر والتاريخ ولا يعمل إلا عبر feed مرخص. | P1 | Planned |
| US-12 | أريد إضافة/تصحيح/سحب requirement واعتماد القائمة قبل قرار حاسم. | P1 | Foundation/Partial؛ التدفق وحارس revision منفذان وتبقى اختبارات beta على PostgreSQL |

## 4. التدفقات

### أ. Onboarding والأدلة

```text
Sign in -> choose language -> create profile
        -> manual fact OR upload PDF/DOCX/LinkedIn ZIP
        -> extracted facts + source/confidence
        -> confirm / correct / unconfirm [API implemented]
        -> verified profile quality
```

لا تعتبر عملية الرفع موافقة على الحقائق. الملف الخام غير محتفظ به حاليًا؛ عند
إضافة object storage يجب أن يظهر للمستخدم وقت الحذف وسياسة الاحتفاظ.

### ب. تحليل وظيفة

```text
Paste description (+ optional reference URL)
 -> deny-by-default source policy
 -> extract mandatory/preferred requirements
 -> user adds/corrects/retires and attests current list
 -> match confirmed facts only
 -> coverage components + explicit blockers + unknowns
 -> apply_now | improve_then_apply | low_return | need_information
```

URL لا يؤدي إلى outbound request. نتيجة الجاهزية `low|medium|high` مع ثقة
وأسباب، وليست احتمال مقابلة.

### ج. المستند الآمن

```text
Select job and language
 -> generator proposes claim units [planned]
 -> server validates each claim against confirmed evidence [implemented]
 -> persist ClaimEvidence + render from accepted claims [implemented]
 -> show diff/provenance [planned UI]
 -> revalidate -> explicit server review/hash [implemented API]
 -> PDF/DOCX export [planned]
```

صفحة المستند الحالية demo وليست دليلًا على اكتمال هذا التدفق.

### د. التقديم والنتيجة

```text
Ready package -> open original platform -> user submits manually
 -> user confirms submitted -> follow-up -> interview/rejection/offer
 -> dashboard and qualified-interview metric
```

العقد الخلفي وTracker المتصل منفذان. لوحة المؤشرات المتصلة تفشل بأمان بحالة
فارغة حاليًا، وتسجيل النتائج والقمع والمتابعات لم تكتمل واجهته بعد.

### هـ. حقوق البيانات

```text
Authenticated user -> GET /v1/me/export -> owner-scoped JSON attachment
Authenticated user -> DELETE /v1/me/data -> database graph deleted
                                      -> anonymous DeletionReceipt retained
```

عند إضافة تخزين ملفات أو analytics أو backups، لا يعد التدفق مكتملًا حتى تمتد
عملية الحذف إليها وتنجح اختبارات الاستعادة والحذف المتأخر.

## 5. معالم 12–16 أسبوعًا

| الفترة | المخرج | بوابة الخروج |
|---|---|---|
| الأسبوعان 1–2 | **تثبيت الـfoundation:** استكمال ربط jobs/dashboard بعد ربط applications، إزالة fallback المضلل، توحيد OpenAPI/TypeScript، وE2E للمسار الرأسي | مستخدم مصطنع يكمل profile→import→confirm→analyze→track عبر الواجهة بلا demo |
| الأسابيع 3–5 | **Evidence graph صالح للbeta:** UX مراجعة كامل، extraction عربي/إنجليزي، malware scan، سياسة الملف الخام، واختبارات ملكية/ملفات عدائية | لا تدخل extracted/unconfirmed fact في تحليل أو مستند؛ import corpus يمر |
| الأسابيع 6–8 | **قرار تقديم موثوق:** ontology أولية للوظائف الرقمية السعودية، أوزان ظاهرة، اعتراضات requirement، fixtures انحياز/غموض، قائمة وظائف حقيقية من إدخال المستخدم | التفسيرات قابلة لإعادة الإنتاج ولا تعرض interview probability |
| الأسابيع 9–11 | **حزمة تقديم حقيقية:** مزود توليد معتمد أو deterministic templates، claims pipeline، diff/provenance، قوالب ATS وتصدير PDF/DOCX | صفر claims غير مدعومة في corpus العدائي؛ موافقة بشرية قبل export |
| الأسابيع 12–13 | **النتائج والمتابعات:** ربط إدخال outcomes، reminders، dashboard والمقياس الشمالي، وإزالة مسارات demo من بيئة beta | كل submitted/outcome مؤكد من المستخدم ومربوط بنسخ المستندات |
| الأسابيع 14–16 | **بوابة beta:** `AuditEvent`، rate limits، monitoring/runbooks، حذف شامل، مراجعة أمن وWCAG، قرار PDPL/النقل، وpilot مضبوط | موافقات الخصوصية والأمن، rollback مجرب، ولا بيانات حقيقية قبلها |

يمكن ضغط الخطة إلى 12 أسبوعًا بتوازي العمل على الأدلة والمطابقة، ثم المستندات
والtracker، لا بحذف بوابات الحقيقة أو الخصوصية. البحث المرخص ليس شرطًا لإطلاق
MVP إذا بقي الإدخال اليدوي ممتازًا؛ auto-apply خارج النطاق.

بالتوازي: 20–30 مقابلة نوعية في الأسابيع 1–4، ثم concierge/pilot حتى 50
مستخدمًا في الأسابيع 8–16. تختبر أسعار 39/69/99 ريالًا بعد إثبات اكتمال التدفق
والاستعداد للدفع، ولا تعتمد قبل بيانات فعلية.

## 6. تعريف جاهزية الـbeta

- يعمل المسار الرأسي بالعربية والإنجليزية على الهاتف ولوحة المفاتيح دون بيانات
  demo أو fallback صامت.
- كل claim نهائي ينجح في validator ويمكن تتبعه إلى حقيقة مؤكدة؛ لا أرقام مخترعة.
- لا outbound fetch لمنصات محظورة، ولا cookies أو credentials أو auto-submit.
- التصدير PDF/DOCX والمراجعة والتقديم اليدوي واضحة ومختبرة.
- export/delete وownership و`AuditEvent` والحذف من كل مخزن اجتازت اختبارات E2E.
- observability وincident response والنسخ الاحتياطية والاستعادة تعمل دون PII في
  logs.
- اكتملت بوابة PDPL ونقل البيانات والمورّدين، أو اختيرت استضافة بديلة معتمدة.
- اتفق الفريق على baseline للمقياس الشمالي ومؤشرات الحماية، لا على عدد الطلبات.
