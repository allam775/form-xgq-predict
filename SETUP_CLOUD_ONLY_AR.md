# XGQ Predict v0.2 — تفعيل الأتمتة السحابية من دون جهازك

## ما تم تجهيزه، وما لا يجب ادعاؤه

- الواجهة الجديدة مستقلة عن XGQ Analyzer ولا تعتمد على تشغيل خادم Python على الكمبيوتر.
- Cloudflare Worker + D1 هما مكان تقديم الموقع والبيانات للزوار.
- ملف `.github/workflows/refresh-online.yml` يتولى **من خوادم GitHub** تشغيل Python، اكتشاف مواسم StatsBomb المجانية، جمع التسديدات، التحقق من الجودة، تصدير SQL، تحديث D1 ثم نشر الواجهة مرتين يوميًا، الساعة 06:23 و18:23 بتوقيت UTC (وقد تتأخر المهام المجدولة).
- لا تصبح الأتمتة مفعلة حتى يُرفع المشروع إلى مستودع GitHub منفصل وتُضاف الأسرار الثلاثة ويُشغّل الـWorkflow بنجاح.
- StatsBomb Open Data تاريخي وانتقائي؛ تحديث البايبلاين يوميًا **لا يعني** وصول تسديدات 2026–2027. إذا انعدمت الإحصائيات الحديثة سيعرض الموقع التغطية الناقصة دون اختلاق احتمالات.
- لعرض الشعارات الرسمية، أضف فقط روابط الصور المسموح بإعادة عرضها مع تفاصيل الترخيص في `config/club_logos.json`؛ الأيقونات الافتراضية داخل الواجهة عامة وليست شعارات رسمية.

## أ — تحديث التصميم على موقعك الحالي فورًا من CMD

1. استخدم ملف `FORM_XGQ_v02_UI_PATCH.zip`، وفك ضغطه **داخل** مسار `FORM_XGQ_Standalone` القديم. يحوي `site/` وتعديلات الكود والـWorkflow، **ولا يحتوي** `wrangler.jsonc` وبالتالي لا يستبدل قاعدة Cloudflare التي أنشأتها.
2. داخل المجلد (CMD):
   ```cmd
   py -3.12 -m unittest discover -s tests -q
   node --check site\app.js
   node tests\test_worker.mjs
   npm run deploy
   ```
3. حدّث صفحة `https://xgq-predict-standalone.ahmedalam778.workers.dev` باستخدام Ctrl+F5. **لا تستخدم** `npm run db:init` مجددًا ما لم تتغير بنية الجداول؛ الإعداد السحابي الموجود يظل محفوظًا.

## ب — تشغيل الأتمتة أونلاين مرة واحدة

1. أنشئ مستودعًا جديدًا، مستقلًا وعامًا (Public) في GitHub باسم مثل `form-xgq-predict`. لا ترفع مصادر خاصة أو بيانات من مزود غير مرخّص. المستودع العام يستخدم GitHub-hosted standard runners دون رسوم الاستخدام المعتادة؛ راجع سياسات GitHub الحالية.
2. ضع **كامل محتويات المشروع v0.2** في المستودع، بما فيها المجلد المخفي `.github/workflows`. لو عندك Git من CMD وبدأت بمجلد غير مرتبط بمستودع:
   ```cmd
   git init -b main
   git add .
   git commit -m "feat: independent cloud XGQ prediction platform"
   git remote add origin https://github.com/YOUR_GITHUB_USERNAME/form-xgq-predict.git
   git push -u origin main
   ```
   غيّر `YOUR_GITHUB_USERNAME` لاسمك، وأنشئ المستودع الفارغ أولًا من GitHub. لو رفض `git push` قد تحتاج تسجيل الدخول عبر Git Credential Manager.
3. من Cloudflare Dashboard أنشئ API token بصلاحيات **Workers Editor / Workers Scripts Edit** و**D1 Edit** لحسابك فقط. لا تستخدم Global API Key. رابط توثيق رسمي: https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/ .
4. من المستودع على GitHub: Settings → Secrets and variables → Actions → New repository secret. أضف ثلاثة أسرار:
   - `CLOUDFLARE_API_TOKEN`: قيمة التوكن الخاص بالنشر. **لا ترسل قيمته لأحد ولا تضعه في السورس**.
   - `CLOUDFLARE_ACCOUNT_ID`: معرّف الحساب من `npx wrangler whoami` في حسابك.
   - `CF_D1_DATABASE_ID`: معرّف قاعدة D1 الموجودة حاليًا من أمر `wrangler d1 list`، **ولا تنشئ قاعدة ثانية**.
   يمكن اختيارياً ضبط `XGQ_SHOT_FEED_URL` فقط لمصدر بيانات تملكه أو لديك تصريح نشر وإعادة استخدام واضح له.
5. من Actions → **Cloud-only XGQ research refresh** → Run workflow → شغّله على `main`. راقب خطوات **Collect**, **Publish verified cloud snapshot** و**Deploy UI and D1 API**. النجاح هنا هو الاختبار الحقيقي للأتمتة.
6. بعد ذلك سيكرر GitHub تشغيل المهمة تلقائيًا مرتين يوميًا. لا يعتمد على الكمبيوتر، وليس عليك فتح CMD للتحديثات الدورية.
7. تحقق من الموقع عبر:
   ```cmd
   curl -i "https://xgq-predict-standalone.ahmedalam778.workers.dev/api/health"
   curl -i "https://xgq-predict-standalone.ahmedalam778.workers.dev/api/forecasts"
   ```
   قد يعرض `forecasts: []` حتى بعد نجاح التحديث إذا كانت المدخلات الحديثة غير كافية. تحقق من `coverage` و`collection` ووقت `generated_at`.

## مصادر مجانية مع مراعاة الحقوق

| المصدر | ما نوظفه | القيد |
|---|---|---|
| [OpenFootball football.json](https://github.com/openfootball/football.json) | جداول ونتائج عامة بترخيص public domain/CC0 | مصدر الجدول الأصلي قد يتأخر |
| [StatsBomb Open Data](https://github.com/hudl/open-data) | قيم xG لكل تسديدة بمواسم مختارة | لا يقدم live لكل الدوريات، وعند نشر التحليل يجب الالتزام بشروط المصدر وإسناده وإظهار شعاره من Media Pack |

إذا احتجنا «توقعات هذا الأسبوع» مبنية فعلًا على XGQ في الدوريات الخمسة، فلا يكفي هذان المصدران حاليًا. لابد من العثور على مصدر أحدث **مرخّص** يتيح xG لكل تسديدة، أو التفاوض على إذن استخدام، أو إضافة بيانات أصلية يمتلكها المشروع. لا تستبدل نتائج المباريات بـXGQ مزيف.
