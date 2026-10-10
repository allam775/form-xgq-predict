# FORM / XGQ Predict — تركيب موصل 365Scores للموقع الشخصي (v0.3.1)

**الحالة:** اختبار كود محلي ناجح؛ الاتصال الفعلي بـ365Scores من GitHub لم يُختبر. **الموصل غير مفعّل افتراضيًا.** حماية Cloudflare Access لا تعطي ترخيصًا تلقائيًا لاستعمال API، ولذلك راجع شروط المصدر قبل تشغيل الجمع التلقائي.

## 1) التركيب الآمن (CMD على Windows)

ادخل مشروعك:

```cmd
cd /d "%USERPROFILE%\Downloads\FORM_XGQ_Standalone_Cloud_D1_v0_1\FORM_XGQ_Standalone"
git status
git pull --ff-only origin main
```

بافتراض أن الملف المحمّل اسمه `FORM_XGQ_365_Private_Connector_PATCH.zip` داخل Downloads:

```cmd
copy engine\collect.py engine\collect.py.bak
copy .github\workflows\refresh-online.yml refresh-online.yml.bak
tar -xf "%USERPROFILE%\Downloads\FORM_XGQ_365_Private_Connector_PATCH.zip" -C .
py -3.12 -m unittest discover -s tests -q
node tests\test_worker.mjs
```

المتوقع في هذه النسخة: 26 اختبار Python ناجح + 7 اختبارات Worker ناجحة. لو فشل الاختبار توقّف وأرسل سجل الخطأ.

## 2) رفع الموصل مع إبقائه معطّلًا

```cmd
git add engine/collect.py engine/provider365.py scripts/sanitize_public_history.py tests/test_provider365.py config/365_teams.json config/365_aliases.json .github/workflows/refresh-online.yml CONNECT_365_AR.md
git commit -m "feat: prepare private-only 365Scores shot connector"
git push origin main
```

لم نغيّر `wrangler.jsonc` أو قاعدة D1. ما دامت GitHub Actions variables الخاصة بالموصل لم تُضبط، سيظل تشغيل StatsBomb/OpenFootball الأصلي كما كان.

## 3) إعداد الفرق

`config/365_teams.json` يبدأ `[]`، وهذا مقصود. يلزم **معرّف رقمي حقيقي** للفريق على 365Scores (لا نخمن المعرفات):

```json
[
  {"team_id":"ACTUAL_NUMERIC_TEAM_ID", "league":"en.1"}
]
```

القيمة `ACTUAL_NUMERIC_TEAM_ID` مثال فقط: ضع مكانها الرقم الحقيقي عند معرفته. لمواءمة أسماء الأندية: `config/365_aliases.json` مثل `{"Arsenal":"Arsenal FC"}`.

## 4) التشغيل الخاص (فقط عندما يكون الجمع المبرمج مسموحًا للمستخدم)

هذه المتغيرات **لا تثبت الحق القانوني**؛ هي مفاتيح تفعيل تقنية. لا تفعّلها إلا بعد التحقق من أن الوصول والجمع مسموحان، وأن Cloudflare Access يحمي الإنتاج وكل المسارات.

```cmd
gh variable set XGQ_365_TEAMS_FILE --body "config/365_teams.json"
gh secret set XGQ_365_ACCESS_AUTHORIZED --body "true"
gh secret set XGQ_365_PRIVATE_ONLY --body "true"
```

في الوضع الخاص **لا تضبط** `XGQ_365_PUBLICATION_ALLOWED=true`.

بعد تعديل ملفات الفرق والتزامها إلى GitHub:

```cmd
gh workflow run refresh-online.yml --ref main
gh run list --workflow refresh-online.yml --limit 3
```

لأن 365Scores ليس مصدرًا رسميًا مفتوح الترخيص هنا، لا يوجد ضمان لثبات استجاباته أو توافر xG الفردي. وعند HTTP 401/403/429 يتوقف الموصل دون محاولات تجاوز.

## 5) نقطة لم نحلها بعد — الاحتفاظ بسجل 365 عبر التشغيلات

في النسخة الحالية، السجلات غير المفتوحة لا تُحفَظ في مستودع GitHub العام؛ فهي متاحة لحساب التوقعات ضمن تشغيل GitHub الحالي فقط. **الاحتفاظ التراكمي الخاص في Cloudflare D1 لم يُضَف بعد**. هذا قد يمنع اكتمال حد أدنى من تاريخ XGQ حتى إذا نجح الاتصال. قبل الاعتماد على التوقعات اليومية نحتاج حفظًا خاصًا مستمرًا، بعد اختبار الرد الحقيقي وتأكيد السماح بتخزينه.

## أمان وخصوصية

- لا ترفع مفاتيح، كوكيز، أو ملفات خام غير مصرَّح بها إلى GitHub العام.
- خليك مفعّل Cloudflare Access على **All traffic**، واحمِ `/api/*` كذلك.
- اسم GitHub repository عام؛ حماية الموقع لا تجعل ملفات المستودع خاصّة.
- لا يوجد تجاوز لحجب، أو تدوير هويات، أو تحايل على حدود الاستخدام.
