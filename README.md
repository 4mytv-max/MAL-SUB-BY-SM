# MAL SUB BY SM

Stremio / Nuvio subtitle addon — Msone + Team GOAT + Movie Mirror, മൂന്ന് site-ലെയും Malayalam subtitles ഒറ്റ addon-ൽ.

## എങ്ങനെ work ചെയ്യുന്നു (live vs daily refresh)
- **Msone — LIVE**: ഓരോ subtitle request-ലും official Msone addon API-യിൽ നിന്ന് നേരിട്ട് എടുക്കുന്നു. Site-ൽ പുതിയ subtitle വന്നാൽ ഉടൻ addon-ലും കിട്ടും. (1-hour cache ഉണ്ട്, repeated opens fast ആയിരിക്കും.)
- **Team GOAT + Movie Mirror — DAILY refresh**: ഈ രണ്ട് site-ലും IMDb id വെച്ച് live search ചെയ്യാൻ പറ്റില്ല (അതുകൊണ്ട് index file ആണ് ഉപയോഗിക്കുന്നത്). എല്ലാ ദിവസവും **രാത്രി 12:00 AM IST**-ക്ക് `tools/crawl_teamgoat.py`, `tools/crawl_moviemirror.py` എന്നിവ auto-run ആയി പുതിയ subtitles index-ൽ ചേർക്കുന്നു.
- സത്യസന്ധമായ ഒരു കാര്യം: Movie Mirror site-ൽ ഇടയ്ക്ക് anti-bot protection (challenge page) വരുന്നുണ്ട് — അന്ന് refresh പാതിയിൽ നിൽക്കാം. Script checkpoint-ൽ നിന്ന് resume ചെയ്യും, അതുകൊണ്ട് അടുത്ത ദിവസങ്ങളിൽ ബാക്കി കൂടി index-ൽ കയറും. Team GOAT refresh stable ആണ്.
- ആദ്യത്തെ subtitle open 1–3 second എടുത്തേക്കാം (live Msone lookup കാരണം) — അതിന് ശേഷം cache കാരണം instant ആണ്.

## Files
- `app.py` — Flask addon (subtitle-only, catalog ഇല്ല)
- `requirements.txt` — flask, requests, gunicorn
- `data/teamgoat_index.json` — Team GOAT subtitle index (daily refresh)
- `data/moviemirror_index.json` — Movie Mirror subtitle index (daily refresh)
- `tools/crawl_teamgoat.py` / `tools/crawl_moviemirror.py` — daily refresh scripts (non-interactive, വീണ്ടും run ചെയ്യാം)

## Deploy (phone-ൽ Chrome ഉപയോഗിച്ച്)

**1. GitHub repo ഉണ്ടാക്കൂ**
- github.com → New repository → പേര്: `mal-sub-by-sm` (Public) → Create
- `Add file` → `Upload files` → ഈ ഫയലുകൾ upload ചെയ്യൂ (folder structure അതേപടി):
  - `app.py`
  - `requirements.txt`
  - `data/teamgoat_index.json`
  - `data/moviemirror_index.json`
  - `tools/crawl_teamgoat.py`
  - `tools/crawl_moviemirror.py`
- Commit ചെയ്യൂ

**2. Render-ൽ service ഉണ്ടാക്കൂ**
- dashboard.render.com → New → Web Service → GitHub repo `mal-sub-by-sm` select ചെയ്യൂ
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Free plan → Create Web Service → deploy കഴിയുന്നത് വരെ wait ചെയ്യൂ (2–5 min)

**3. Stremio / Nuvio-യിൽ install ചെയ്യൂ**
- Addon URL: `https://<നിങ്ങളുടെ-service-പേര്>.onrender.com/manifest.json`
- Stremio: Addons → search bar-ൽ URL paste → Install
- Nuvio: Settings → Addons → URL paste → Install

Subtitle list-ൽ `[Msone]`, `[Team GOAT]`, `[Movie Mirror]` എന്ന label-ൽ ഏത് site-ലെ subtitle ആണെന്ന് കാണാം.

## Daily refresh-ന് ശേഷം
Refresh script-കൾ പുതിയ `data/*.json` ഉണ്ടാക്കുമ്പോൾ, ആ രണ്ട് JSON file GitHub repo-യിലെ `data/` folder-ൽ upload ചെയ്താൽ Render auto-redeploy ആകും — പിന്നെ പുതിയ subtitles addon-ൽ കിട്ടും.
