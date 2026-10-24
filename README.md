# Geotechnical News Desk — ISSMGE Magazine

Every morning GitHub automatically:

1. reads 26 websites (societies, hazard agencies, trade press) and 76 Google News
   searches listed in `config.yaml`. The searches cover seven English-language editions
   (UK, US, India, Australia, South Africa, Singapore, UAE) plus Arabic, French, Spanish,
   Portuguese, German, Italian, Turkish, Hindi, Indonesian, Chinese and Japanese;
2. scores each new story for geotechnical relevance (78 weighted keywords) and removes duplicates;
3. asks Claude to rate each story 1–5, place it under one of the magazine's eight themes,
   suggest a use (news brief, feature lead, Academia-to-Industry topic, regional insight,
   watch only), write the geotechnical angle, and translate non-English headlines;
4. saves the digest permanently, rebuilds the website and *(optionally)* e-mails it.

Website: **https://monabadr12.github.io/geotech-news/**

## The website

| Page | What it is for |
|---|---|
| **Latest** | Today's digest, grouped by theme (strongest theme first), with filters for rating, use and keywords. |
| **Archive** | Every digest ever produced, grouped into **three-month issue windows** that match the magazine's quarterly cycle. |
| **Issue collection** (one per quarter, e.g. *Q4 2026*) | All stories from the quarter in one place: theme overview table, "strongest leads" shortlist, all stories by theme, list of daily digests, **spreadsheet download (CSV)** and print / save as PDF. This is the page to plan an issue from. |
| **Search** | Search all archived stories by keyword, issue window, theme, use and rating; export the results as a spreadsheet. |
| **Method & sources** | What is scanned, how stories are scored, and which sources failed on the latest run. |

### How the archive works

* Each scan saves its stories to `data/digests/YYYY-MM-DD.json`. **These files are the archive** —
  they are kept forever in the repository (and in its Git history).
* Everything in `docs/` (the website) is rebuilt from those files on every run, so the design can be
  changed at any time without losing anything.
* Issue windows are calendar quarters by default (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec). If the magazine's
  cycle starts in a different month, change `issue_start_month` under `magazine:` in `config.yaml`.
* The spreadsheets (`docs/exports/2026-Q4.csv` etc.) open directly in Excel and keep Arabic, Chinese and
  other scripts intact.

---

## Setup (one time, about 15 minutes)

The files are already in this repository. What remains is done on github.com.

### 1. Put the workflow live
The scheduled scan only runs from the repository's **main** branch. Merge this work into `main`
(open the pull request on GitHub and press **Merge**).

### 2. Allow the workflow to save results
**Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**

### 3. Add your Anthropic API key as a GitHub secret
The key lets the scanner call Claude. A *secret* is stored encrypted by GitHub: nobody can read it back
(not even you), it never appears in the code or the logs, and only the workflow can use it.

1. **Get a key.** Go to <https://console.anthropic.com>, sign in, open **API Keys** and press
   **Create Key**. Name it e.g. `geotech-news`, then copy the key (it starts with `sk-ant-`).
   The key is shown only once. API use is billed separately from a Claude.ai subscription, so
   add a payment method or credits under **Billing**. A monthly spend limit is a sensible safeguard
   (Settings → Limits).
2. **Open the repository's secrets.** On github.com open `monabadr12/geotech-news` →
   **Settings** (top bar of the repository) → in the left menu **Secrets and variables** → **Actions**.
3. Press **New repository secret**.
4. **Name:** `ANTHROPIC_API_KEY` (exactly this, in capitals).
   **Secret:** paste the key. Press **Add secret**.
5. You should now see `ANTHROPIC_API_KEY` listed under *Repository secrets*. To change the key later,
   press the pencil icon next to it; to stop using it, delete it.

Never paste the key into `config.yaml`, a commit, an issue or an e-mail: the repository is public.
Without a key the scanner still works, ranking stories by keywords only.

The configured model is Claude Haiku (`claude-haiku-5-5`), the lowest-cost model, which is ample for this
triage. A daily run sends about 130 short headlines, so the cost is typically a few cents per day.

### 4. Turn on the website
**Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/docs`
→ Save.** After a minute or two the site is live at the address above.

### 5. Run the first scan
**Actions** tab → **Geotechnical news scan** → **Run workflow**. It takes 2–4 minutes; then open the website.

### 6. Check the sources
At the bottom of the digest, open **Scanner notes and sources that failed**. For any failed site find its
RSS feed address (often `site.com/feed/` or an RSS icon) and replace the address in `config.yaml`.
If AI triage did not work, the same panel says why (for example, a rejected API key).

## Optional: e-mail delivery
Add these secrets the same way as the API key: `SMTP_HOST`, `SMTP_PORT` (usually 587), `SMTP_USER`,
`SMTP_PASSWORD`, `MAIL_TO` (comma-separate several addresses).
For Gmail: host `smtp.gmail.com`, and create an *App password* in your Google account
(2-step verification required) to use as `SMTP_PASSWORD`.

## Changing things
* **Sources, searches, keywords, themes, limits:** all in `config.yaml` (edit it on GitHub with the pencil icon).
  Adding a language is one line under `extra_queries`.
* **Schedule:** `.github/workflows/scan.yml` (daily at 05:00 UTC; the file shows how to switch to every two days).
* **Look of the website:** `assets/style.css`. To rebuild the site without scanning, run `python site_builder.py`.

## Files
| File | Purpose |
|---|---|
| `scanner.py` | Reads the sources, scores and triages stories, saves the digest. |
| `site_builder.py` | Builds the website in `docs/` from the archive in `data/digests/`. |
| `config.yaml` | All settings. |
| `assets/` | Website style sheet and script. |
| `data/digests/` | **The permanent archive**, one file per day. |
| `data/seen.json` | Stories already shown (45-day memory, so nothing repeats). |
| `docs/` | The generated website (do not edit by hand). |

## Notes
* Headlines link to the original publishers; the digest reproduces no article text beyond the short feed
  summary. Treat stories as leads and go to the primary source before publishing.
* Some sites block automated readers or have no feed; Google News searches usually still catch their stories.
