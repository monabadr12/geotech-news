# Geotechnical News Desk — ISSMGE Magazine

Every morning (05:00 Cairo time) GitHub automatically:

1. reads specialist, society, hazard-agency and trade-press websites, worldwide Google News searches in English
   (UK, US, India, Australia, South Africa, Singapore, UAE editions, and searches for Nigeria, East Africa, Ghana and
   New Zealand) and 16 other languages — Arabic (Egypt, UAE, North Africa), French, Spanish (Spain, Mexico, Colombia,
   Chile, Peru, Argentina), Portuguese, German, Italian, Turkish, Hindi, Indonesian, Chinese, Japanese, Vietnamese,
   Korean, Russian, Polish and Persian — and new papers from 25 geotechnical journals;
2. scores each story for geotechnical relevance in any of those languages, merges repeated reports of the same event
   and balances the digest across the magazine's eight themes;
3. asks Claude to rate each story 1–5, place it under a theme, suggest a use (news brief, feature lead,
   Academia-to-Industry topic, regional insight, watch only), write the geotechnical angle in its own words, translate
   non-English headlines, read **where the story happened** (country and town, region or site) and name the
   **primary source to check** the facts with, and links any story that **follows up an earlier one** (the inquiry
   into last month's landslide) to that event;
4. saves the digest permanently, rebuilds the website, Excel workbooks and Word report, refreshes the **events
   calendar** once a week, drafts the **issue brief** when one is due, and e-mails an **alert** for new 5/5 stories
   and, on Mondays, the **weekly summary** to the editorial team.

Website: **https://monabadr12.github.io/geotech-news/**

## The website

| Page | What it is for |
|---|---|
| **Latest** | Today's digest, grouped by theme (strongest theme first), with filters for rating, use and keywords. Beside the news: this week and its summary, upcoming events and call-for-papers deadlines, and the developing stories with new reports. |
| **Archive** | Every digest ever produced, grouped into **three-month issue windows** that match the magazine's quarterly cycle, and the latest **weekly summaries** (each week's page lists that week's top stories, developing stories, regional coverage, events and research). |
| **Issue collection** (one per quarter, e.g. *Q4 2026*) | All stories and research papers from the quarter in one place: the **issue brief**, the **suggested table of contents** (which sections the scanner feeds), theme overview, regional coverage (with a link to the gaps on the world map), "strongest leads" shortlist, the quarter's developing stories, upcoming events and deadlines (current quarter), all stories by theme, new research, list of daily digests, **Excel workbook**, the **shared planning sheet** (once it is set up), CSV, and print / save as PDF. This is the page to plan an issue from. |
| **Search** | Search all archived stories and research papers by keyword (place names included), issue window, theme, use and rating; results show where each story happened and the developing story it belongs to; export the results. |
| **Developing stories** | Events, projects and sites reported more than once, each with its timeline: the failure, then the response, the inquiry, the repair and the court case. Active and earlier ones, with a filter. |
| **World map** | Stories by the country they are about, for any issue window, the last 30 days or the whole archive, with the ISSMGE regions and the member-society countries that had no stories (the gaps), a table view and a theme filter. |
| **Events** | Conferences, symposia and courses with their call-for-papers deadlines: ISSMGE events and others, a calendar feed to subscribe to, and the **Refresh calendar** button. |
| **Trends** | Charts of stories per month and per quarter by theme, theme shares over time, rising keywords, regions, editorial uses and sources — material for editorials and the year in review. Each chart has hover details and a table view, and the numbers can be downloaded. |
| **AI assistant** | Chat with Claude about the archive: find stories, compare quarters, follow a developing story ("What is the latest on …?"), look up conferences and deadlines, get a recommended line-up for an issue or a draft in its own words (ending with a *Check before publishing* list), and attach PDF or Word documents (calls for papers, drafts, reports) to discuss them alongside the news. Needs the one-time connector setup below. |
| **Method & sources** | What is scanned, how stories are scored, located and linked, how events are found and e-mails sent, how to use the stories without breaching copyright, and which sources failed on the latest run. |

Every page has a **Scan now** button (see below).
The footer links the **Website report (Word)**.

### Issue brief (Word)
For each issue window Claude drafts a brief for the editorial meeting (`docs/briefs/2026-Q4-issue-brief.docx`, linked
from the issue page and the Archive). It opens with a **proposed table of contents** that follows the
[suggested issue layout](#suggested-issue-layout): for every section the scanner fills, exactly as many stories, papers,
events or developing stories as the section has slots, each with a one-line reason and whom to check it with (each item
is used once, a developing story and its reports counting as one, and the events section takes only events still to
come when the issue appears); for the
sections that come from ISSMGE or the editor, a short *to collect* checklist with pointers from the quarter's data (the
TC symposia and ISSMGE events for *Technical Committees Activities* and *ISSMGE Highlights*, the member-society countries
with no stories for *Global News from Member Societies*, Digital Geotechnics stories for *Education & Innovation*). Then
come an overview of the quarter, a proposed line-up for every theme (with
the angle, format and reason for each pick), about five feature leads with the kinds of experts to approach,
Academia-to-Industry topics that pair news with research papers, a regional-balance check, gaps worth covering and a
watch list, then the quarter's **developing stories** and the **events and deadlines** from the start of the quarter to
six months after it (both listed as they stood when the brief was drafted; Claude also reads them for its feature leads
and watch list). Every pick links to its source and names the primary source to check it with, and the brief opens
with the five steps of *Before you use a story*.
* **Automatically:** a draft in the last 21 days of each quarter, refreshed weekly, and the final brief the day after the
  quarter closes (settings under `brief:` in `config.yaml`).
* **On demand:** press **Generate / update brief** on the issue page. It opens the *Issue brief* workflow on GitHub:
  press **Run workflow** (leave *window* empty for the current quarter, or type e.g. `2026-Q3` and tick *final*). The page
  follows the run and says when the brief is ready.
* It uses the same `ANTHROPIC_API_KEY` secret as the scan; Claude Opus writes it. Should Claude Opus decline (a rare
  false alarm of its safety filters), the API passes the request to the fallback model Anthropic recommends and the
  brief says which model wrote it. Briefs written before 26 October 2026 have no table of contents and keep their
  numbering.

### Suggested issue layout
The magazine (relaunched in March 2024 as a quarterly e-magazine of about 50–60 pages) has no fixed layout, so the news
desk suggests one. Most sections come from ISSMGE; the scanner feeds the ones marked *scanner* or *mixed*. It is the
default `issue_layout:` in `config.yaml`:

| # | Section | Source | Items from the scanner | Pages | What goes there |
|---|---|---|---|---|---|
| 1 | Cover story | scanner | 1 | 4–6 | a developing story or a 5/5 feature lead |
| 2 | Welcome from the President | society | – | 1–2 | the President's message |
| 3 | Message from the Editor | editor | – | 1 | the editor's introduction |
| 4 | From the Board / Vice-Presidents' reports | society | – | 4–8 | Board and regional Vice-Presidents' reports |
| 5 | ISSMGE Highlights | society | – | 3–4 | ISSMGE news; dates of ISSMGE events from the events calendar |
| 6 | Geotechnics in the News | scanner | 10 | 4–6 | 8–12 short items across the eight themes |
| 7 | Lessons from the Field | scanner | 1 | 3–4 | a developing story: failure → inquiry → repair |
| 8 | From Research to Practice | scanner | 2 | 2–3 | research papers |
| 9 | Global News from Member Societies + Regional Insight | mixed | 6 | 4–6 | member societies' news, plus one story per ISSMGE region (the world map shows the gaps) |
| 10 | Technical Committees Activities | society | – | 3–5 | TC reports; TC symposia from the events calendar |
| 11 | Young Members' Arena | society | – | 2 | young members' news |
| 12 | Education & Innovation | mixed | 2 | 2–3 | education news, plus Digital Geotechnics stories |
| 13 | Corporate Associates Corner | society | – | 3–6 | corporate associates' news |
| 14 | Heritage / Time Capsule | society | – | 1–2 | the profession's history |
| 15 | In Memory | society | – | as needed | obituaries |
| 16 | Upcoming Events & Calls for Papers | scanner | 8 | 1–2 | conferences and deadlines from the events calendar |

The issue pages show it as **Suggested table of contents**, the issue brief proposes the items for it, and the shared
planning sheet builds its plan tabs from it. **To change it**, edit `issue_layout:` in `config.yaml` on GitHub (pencil
icon): rename, reorder, add or remove sections. Each section has a `name`, a `source` (`scanner`, `society`, `editor` or
`mixed`), `slots` (how many items the scanner proposes: 0 for society and editor sections, at least 1 for scanner
sections), `pages` (text such as `"4-6"` or `"as needed"`) and `use` (what goes there and which part of the news desk
feeds it; Claude reads it when it chooses the items). The website shows the change a minute or two after you save, the
next brief follows it, and the planning sheet adds rows for new sections the next morning. A section that cannot be read
is repaired or left out with a note in the log, and if none can be read the layout above is used, so a typo never stops
the scan.

### World map
During triage Claude reads the country each story is about (an ISO code such as `CO` or `GB`) and the town, region or
site it names: where the event, project or site is, which is often not the outlet's country or the Google News edition
that found the story. A story about several countries, or a general market or research result, counts as global.
Stories archived before this was added (or whose triage failed) are located in batches after each scan, newest first;
the scan's own stories that Claude did not rate come first, while their feed summaries are still there to read.
The **World map** page plots the stories by country, compares them with the member-society countries of ISSMGE's six
regions and marks the member countries with no stories in the period, so regional gaps are easy to spot when planning an
issue. The issue pages and the weekly summaries show the same regional figures. Settings and the ISSMGE member lists are
under `map:` in `config.yaml`; the lists for Africa and Europe are marked `to_check: true` until they have been checked
against <https://www.issmge.org/member-societies>. The outlines come from Natural Earth (`assets/world.json`, made by
`tools/make_world.py`).

### Developing stories
Every scan, Claude compares the day's new stories with the archive of the last year and links a story to an earlier one
only when both are about the same event, project or site (the same landslide, dam or tunnel in the same place, not merely
a similar hazard in the same country), naming the stage it reports: the event, response and recovery, investigation and
inquiry, repair and reconstruction, legal and policy, or an update. Claude Sonnet makes the links and says which cases it
is unsure of (two place names in one region, a translated headline that may or may not name the same site); up to 8 of
those per scan (`max_checks`) are read again by Claude Opus, each against its own closest earlier stories, and Opus's
decision stands. `check_model: ""` turns this check off, and if the check fails, Sonnet's reading is kept. Without
Claude, a cautious headline match links reports found within 30 days that name the same place and the same kind of
event (a sinkhole is not a follow-up of a landslide in the same city). Story cards everywhere carry a **Developing
story** chip that opens the timeline on the **Developing stories** page. Long-running events make good features: by
the time the cause is known and the repair designed, the lessons for practice can be told. Settings under
`storylines:` in `config.yaml`. A link is a lead: check each report at its source.

### Events calendar
The **Events** page lists conferences, symposia, courses and webinars for geotechnical engineers, with their
deadlines (calls for abstracts and papers, registration), from two sources:
* **The editors' list, `data/events.yaml`.** Edit it on GitHub (pencil icon, or **Edit the editors' list** on the Events
  page); its first lines explain the format. An event listed there always wins over the same event found by the refresh,
  so this is the place to correct a date or a link. If an entry cannot be read, the Events page says which and why.
* **The regular refresh.** Every 14 days (`refresh_days`) the daily scan asks Claude to read the organisers' calendars
  listed under `events: calendars:` in `config.yaml` (ISSMGE, ITA-AITES, the ASCE Geo-Institute, ISRM, IGS, DFI, BGA,
  ICE and GeoEngineer) with Anthropic's web search and web fetch tools, and keeps what it finds in `data/events.json`.
  Every event must link to a page Claude actually read, and predatory conference series are left out. A site or organiser
  added later to `blocked_domains` or `blocked_organisers` (`events:` in `config.yaml`) disappears from the calendar at the
  next build, along with the events already found there. Web search and web fetch must be allowed for the organisation
  that owns the `ANTHROPIC_API_KEY` (Claude Console → Settings). A refresh that fails leaves the calendar as it was; the
  daily scan tries again two days later (the next day when Claude was only busy), and the Events page says why.
* **What a refresh costs.** It uses Claude Sonnet with web search, every 14 days (`refresh_days`). Each page
  Claude opens is capped (`max_page_tokens`), the research uses prompt caching, and near `max_cost_usd` (US$3) Claude
  stops reading and writes up the events found so far. The log of each run ends with a line giving the tokens,
  searches, pages and estimated cost at list prices. `claude-opus-5-5` (set with `events: model:`) judges a little
  better at twice the price. It is also wise to set a monthly spend limit for the key in the Claude Console.
* **Refresh calendar** on the Events page starts a refresh at any time: it opens the *Events calendar and weekly summary*
  workflow on GitHub, where you choose **refresh the events calendar** and press **Run workflow**. The run fails, and
  the page says so, when nothing was refreshed (no key, or no event passed the checks).
* **Subscribe:** the whole calendar is a feed, `https://monabadr12.github.io/geotech-news/events.ics`, that Outlook,
  Google Calendar or Apple Calendar can subscribe to (the Events page explains how); each event also has **Add to
  calendar**. The Latest and issue pages show the next deadlines and events beside the news.

### Alerts and weekly summary (e-mail)
After each daily scan, one e-mail lists any new story rated 5 / 5 (at most one alert per scan). Every Monday morning the
editorial team receives the **weekly summary** of the week before: the top stories of each theme, other 5 / 5 stories,
developing stories updated that week, regional coverage by ISSMGE region, events and deadlines in the next 60 days, and new
research. Each week's summary is also a page on the website (Archive → **Weekly summaries**), and **Send summary now** on
those pages sends last week's summary at any time. `data/notify.json` records what was sent, so nothing goes out twice.
Settings (which e-mails, the weekday, the rating that triggers an alert) are under `alerts:` in `config.yaml`. Setting up
e-mail is described [below](#e-mail-alerts-and-the-weekly-summary-setup-about-10-minutes).

### Research papers (Academia-to-Industry)
Each scan also asks Crossref (free, no key) for papers newly registered in 25 journals, including *Géotechnique*,
*Géotechnique Letters*, *Canadian Geotechnical Journal*, *ASCE JGGE*, *Soils and Foundations*, *Acta Geotechnica*,
*Computers and Geotechnics*, *Engineering Geology*, *Landslides*, *Tunnelling and Underground Space Technology* and
*Geotextiles and Geomembranes*. Claude rates each for practice and writes one line, in its own words, on why it matters
to practitioners (the abstracts are read for this but no longer saved and never shown: read the paper itself through its DOI link).
Up to 20 papers per digest appear under **New research** on the digest and issue pages, in Search, in the Excel
**Research** sheet and in the issue brief. Add a journal under `research: journals:` in `config.yaml` with its ISSN;
test it with the **Check feeds** workflow (input `{"research": true}` tests every journal).

### Sources that block automated readers
Sites that refuse feed readers or publish no feed (ISSMGE, ICE, GEER, USGS, GeoEngineer, Railway Gazette and others)
are read through Google News searches limited to the site (`site:` searches, which can carry the site's `boost`).
To test a new address before adding it, run the **Check feeds** workflow on GitHub with a JSON input such as
`{"Railway Gazette": ["https://www.railwaygazette.com/rss"]}`; the log marks each address OK or FAIL.

### How stories are categorised
Every headline is matched against English keywords **and** more than 900 terms in 16 other languages
(`multilingual_keywords` in `config.yaml`). Each foreign term counts as its English equivalent —
*glissement de terrain*, *deslizamiento*, *longsor*, *山体滑坡*, *sạt lở đất*, *산사태*, *оползень* and *انهيار أرضي* all
count as "landslide" — and those English concepts decide the theme. For inflected languages a `*` stands for the rest of
the word (`оползн*`, `osuwisk*`). So a story in any covered language is filed under the correct English theme,
even when Claude is not available. When Claude triage runs, it confirms or corrects the theme and translates the headline.
A foreign headline that still has no English translation after the triage is translated at the end of the scan, in one
small extra request that also covers any left untranslated in the digests of the last 45 days (a headline Claude finds
to be in English is marked and not sent again). To do this at any time: **Actions** → **Events calendar and weekly
summary** → **Run workflow** → choose **translate missing headlines** (`python scanner.py --translate-missing`).
After changing the keyword or theme lists, `python scanner.py --reclassify` re-files the stories already archived.

### Excel workbooks
Each issue window has a workbook (`docs/exports/2026-Q4.xlsx`, button **Excel workbook** on the issue page), and there
is one for the whole archive (`geotech-news-archive.xlsx`, on the Archive page). Each contains:
* **Start here** — what each sheet is for, how to use the selectors, colour keys, and links to every sheet and theme.
* **Dashboard (interactive)** — yellow dropdowns for *Theme*, *Suggested use*, *Minimum relevance* and, in the archive
  workbook, *Issue window*. Every key figure, table, chart, the theme × use heat map and the **Top 10 stories** list
  recalculate for the selection.
* **Stories** — every story as a filterable Excel table, colour-coded by theme and rating, with the headline linked to the
  article (Claude's English translation for a foreign story, with the original beside it), the **Primary source to
  check**, and where it happened (**Country**, **Place**) and the **Developing story** it belongs to. Planning columns let
  you work in the file: **Status** (To review / Shortlisted / Commissioned / Published / Not used), **Assigned to** and
  **Editor notes**; the dashboard's planning chart follows the statuses you set.
* **By theme** — a tidy reading view, one collapsible section per theme, best stories first.
* **Research** — the window's new research papers (when there are any).
* **Events** — the events calendar when the workbook was made: open deadlines (with the days left) and the
  upcoming events, each linked to its website.
* **Sources** — which outlets contributed and how relevant their stories were.

The CSV files (issue pages and Search) have the same Primary source to check, Country, Place and Developing story
columns. The **Start here** sheet repeats the five steps of *Before you use a story*.

Tips: downloaded files open in Protected View, so press **Enable Editing** to see the figures. The workbook is rebuilt
after every scan, so save your own copy for the planning columns, or plan together in the
[shared planning sheet](#shared-planning-sheet-google-sheets), which keeps the team's columns.

### How the digest is balanced
No theme may take more than 30 % of a digest (`max_share_per_theme` in `config.yaml`; 18 of 60 stories). Themes take
turns, the theme with the best story first, so every theme that has stories is represented. No website may give more
than 5 stories (`max_per_source`; 0 = no limit): a website keeps its five best, and each place this frees goes to the
next story of the same theme, or, when Claude's translations show that another website reported the same event, to
that website's report. Up to 15 stories from one website go to Claude. Several outlets reporting the same event are
merged into one story, and copies of one story in several languages count once: Vietnam.vn, for example, publishes
each story in Vietnamese, English, Chinese and other languages, and Google News lists every copy, so once Claude has
translated the headlines, copies whose English headlines match are merged and the best one is kept. A second scan on
the same day merges with the morning's digest and re-balances it.

### Website report (Word)
`docs/reports/site-report.docx` is regenerated after every scan: status at a glance, an automatic review of the
latest scan (triage, failed sources, theme balance), source health with suggested fixes, archive figures, regional
coverage on the world map (stories per ISSMGE region and the member societies with none), the most followed developing
stories, research papers, issue briefs, the events calendar (when it was refreshed, the next deadlines), the e-mails
recorded as sent, the change log and open items. The change log and open items are kept in `data/changelog.yaml`.

### How the archive works
* Each scan saves its stories to `data/digests/YYYY-MM-DD.json`. **These files are the archive** —
  they are kept forever in the repository (and in its Git history). Each issue page gathers every story of its
  quarter, so nothing is lost by the time the issue is planned. (The 45-day memory in `data/seen.json` only stops
  the same article being picked up twice; it never removes anything from the archive.)
* Everything in `docs/` (the website, workbooks and report) is rebuilt from those files on every run, so the design
  can be changed at any time without losing anything.
* Issue windows are calendar quarters by default (Jan–Mar, Apr–Jun, Jul–Sep, Oct–Dec). If the magazine's
  cycle starts in a different month, change `issue_start_month` under `magazine:` in `config.yaml`.

## Using the stories in the magazine (copyright)
Every story the news desk finds is a **lead**, not material to reuse. Before you use a story:

1. **Treat the news item as a lead**, not as your source.
2. **Check the facts with the primary source**: the authority, the project owner, the company's press release or the
   official report. Story cards name it as **Check with**.
3. **Write the piece in your own words**, with your own angle; the digest's *magazine angle* is a starting point.
4. **Quote a sentence or two at most**, in quotation marks, naming the publication and linking to it.
5. **For images, use your own**, the project's press-kit photos released for media use, or ask permission. Never reuse
   a source's photos, figures or drawings.

The five steps appear as **Before you use a story** near the top of every digest and issue page (one line, opened
with a click), on the Method & sources page (*Using the stories: copyright*), on the Excel **Start here** sheet, at the
foot of the weekly summary e-mail and page, in the Word website report and in each issue brief.

What the system does to follow them:
* **No publisher's text beyond the headline is published or saved.** The scanner reads the feeds' summaries and the
  papers' abstracts during the scan (for the keyword score and for Claude's reading), but saves every story with an
  empty `summary` and every paper with an empty `abstract`, so neither the current archive files in `data/digests/`
  (public in this repository) nor anything built from them — website pages, search data (`docs/exports/*.json`), CSV
  and Excel files, the Word report, issue briefs, e-mails, the AI assistant's context — contain them. A story without
  an angle shows its headline and source only. `python scanner.py --clear-publisher-text` empties any summaries and
  abstracts left in older digests (it was run once on 25 October 2026 and changes nothing else; running it again is
  safe). *Earlier versions* of the files in the repository's Git history (the digests, workbooks and search data
  committed before 25 October 2026) still hold the feed summaries and abstracts saved until then. Removing them takes a
  history rewrite (for example `git filter-repo`, blanking `summary` and `abstract` in `data/digests/*.json` and
  dropping the old `docs/exports/` files) and a force-push of `main`, which only the repository owner should decide on.
* **Headlines identify the article** and always come with the source's name and a link to the original. Headlines of
  foreign stories are shown in Claude's English translation, labelled *English headline translated by Claude*, with
  the original headline beside it.
* **The magazine angle and the note on why a paper matters are Claude's own words**: the triage prompt forbids copying
  or closely paraphrasing the headline, summary or abstract.
* **Primary source to check**: for each story it rates, Claude names in at most 12 words whom to verify the facts with
  (an authority, the project owner, the company or the body behind the official report; blank when unclear). It is
  shown as *Check with* on story cards, in Search, in the alerts and the weekly summary, as the *Primary source to
  check* column of the CSV and Excel files, in the AI assistant's context and with each story in the issue brief.
  Stories rated before 25 October 2026 have none.
* **The AI assistant** answers and drafts in its own words, never reproduces article text, abstracts or paywalled
  content, quotes at most a sentence or two (in quotation marks, publication named and linked), always lists its
  sources with links, names the primary source to check, ends every draft of a magazine piece with a short **Check
  before publishing** list (facts to confirm, quotes to verify, image rights) and, for images, recommends your own
  photos, press-kit photos or asking permission — never a source's photos, figures or drawings. The **issue brief**
  follows the same own-words, short-quote, primary-source and image rules and shows *Check with* beside every story.
* **No images from the sources**: the website, e-mails and downloads show none, and the scanner does not collect them.

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

**What it costs to run** (rough figures at list prices; the Claude Console's *Usage* page shows the real spend
by model, and *Limits* sets a monthly cap):

| Part | Model (`config.yaml`) | How often | Rough cost |
|---|---|---|---|
| Triage, locating stories, missing headline translations, research papers | Haiku | every scan | a few cents a day |
| Developing stories (linking follow-ups) | Sonnet (`storylines: model:`); the unsure cases checked by Opus (`check_model:`) | every scan | about US$0.05–0.15 a day (US$1.50–4.50 a month, rising as the archive grows) |
| Events calendar refresh | Sonnet (`events: model:`) | every 14 days | about US$0.70–1.50 |
| Issue brief | Opus (`brief: model:`) | a few times a quarter | about US$1–2 each |
| AI assistant | Sonnet by default, chosen per question | each question | about US$0.05–0.10 (more with long chats or PDFs; Opus about twice that) |

Altogether about US$5–9 a month plus the AI assistant. Scanning less often saves little and loses news, because each
scan looks back only 60 hours (`lookback_hours`).

### 4. Turn on the website
**Settings → Pages → Build and deployment → Source: Deploy from a branch → Branch: `main`, folder `/docs`
→ Save.** After a minute or two the site is live at the address above.

### 5. Run the first scan
**Actions** tab → **Geotechnical news scan** → **Run workflow**. It takes 2–4 minutes; then open the website.

### 6. Check the sources
At the bottom of the digest, open **Scanner notes and sources that failed**. For any failed site find its
RSS feed address (often `site.com/feed/` or an RSS icon) and replace the address in `config.yaml`.
If AI triage did not work, the same panel says why (for example, a rejected API key).

## Scan now button
**Scan now** (top right of every page) opens the scan's page on GitHub in a new tab. Press **Run workflow**, then the
green **Run workflow** button. Starting a GitHub job needs a signed-in GitHub user, which you are on github.com, so the
website itself needs no key or token. Back on the website, a notice follows the scan and tells you when the new digest
is ready (about 4 minutes).

## AI assistant (one-time setup, about 5 minutes)
The website is public, so it cannot hold an API key, and GitHub secrets can only be used by GitHub jobs. The assistant
therefore talks to a small connector that runs in **your own Google account**. The connector reads your Anthropic key from
your private Google Doc and passes questions to Claude. The key never reaches the website or this repository.

1. Open <https://script.google.com> and press **New project**. Rename it *Geotechnical News Desk assistant*.
2. Delete the sample code and paste the whole of [`assistant/bridge.gs`](assistant/bridge.gs) (on GitHub, open the file
   and press the copy icon).
3. On line 15, replace `PASTE-THE-LINK-TO-YOUR-KEY-DOCUMENT-HERE` with the link to the Google Doc that holds your key.
   Press **Save** (disk icon).
4. *Optional check:* choose **testConnection** in the function menu at the top and press **Run**. Allow the permissions
   Google asks for. The log at the bottom should show `HTTP 200` and the word *connected*.
5. Press **Deploy → New deployment**, click the gear icon and choose **Web app**. Set **Execute as: Me** and
   **Who has access: Anyone**. Press **Deploy** and allow the permissions. Google warns that the app is unverified because
   you wrote it yourself: choose **Advanced → Go to project**.
6. Copy the **Web app URL** (it ends in `/exec`) and put it in `config.yaml` under `assistant: endpoint:` (or send it to
   Claude to do it). The site rebuilds itself and the assistant connects.

Notes:
* Keep the Google Doc private (Share → *Restricted*). The connector reads it as you, so it does not need to be shared.
* The connector answers up to 100 questions a day (`DAILY_LIMIT` in the script) to protect your Anthropic bill. Setting a
  monthly spend limit in the Anthropic Console is still recommended.
* Optional passcode: in the script's **Project Settings → Script properties**, add `ACCESS_CODE`. The website then asks
  for it once per device.
* After editing the script, use **Deploy → Manage deployments → Edit → Version: New version** to update the existing address.

## E-mail alerts and the weekly summary (setup, about 10 minutes)
The alerts and the Monday summary go out through the first of two routes that is set up. Until one is, nothing is sent:
each run's log shows the e-mail that would have gone out and what is missing.

**Recommended: through the AI assistant's Google connector** (no mail server or password needed; the e-mails come from
your Google account). It uses the connector set up under *AI assistant* above.
1. In your Apps Script project, replace the code with the current [`assistant/bridge.gs`](assistant/bridge.gs) (it now also
   sends e-mail) and keep your link to the key document on line 15. Press **Save**.
2. Open **Project Settings** (gear icon) → **Script properties** → **Add script property**:
   * `NOTIFY_TOKEN` — a long random text, for example 40 letters and digits (a password generator is handy). Without it
     the connector sends no e-mail at all.
   * `MAIL_TO` *(optional)* — the recipients, separated by commas. Leave it out to send to your own address.
3. Choose **testEmail** in the function menu at the top and press **Run** once. Google asks for permission to send e-mail
   as you: allow it. A test e-mail arrives in your inbox.
4. **Deploy → Manage deployments**, press the pencil icon, choose **Version: New version** and **Deploy**. This keeps the
   same web address, so `config.yaml` does not change.
5. On GitHub, add the secret `NOTIFY_TOKEN` (Settings → Secrets and variables → Actions → **New repository secret**) with
   exactly the same text as the Script property.
6. Check it: **Actions** tab → **Events calendar and weekly summary** → **Run workflow** → choose **send a test e-mail** →
   **Run workflow**. The run turns green when the e-mail has gone, and red (with the reason in its log) when it could not.

**Alternative: a mail server.** Add the GitHub secrets `SMTP_HOST`, `SMTP_PORT` (587, or 465 for SSL), `SMTP_USER`,
`SMTP_PASSWORD` and `MAIL_TO` (addresses separated by commas). For Gmail: host `smtp.gmail.com`, port 587, your address
as `SMTP_USER`, and an *App password* (Google Account → Security → 2-Step Verification → App passwords) as
`SMTP_PASSWORD`. When `SMTP_HOST` is set, the mail server is used instead of the connector. Test it with the same
**send a test e-mail** run.

The weekly summary pages have a **Send summary now** button, which starts the same workflow with **send the weekly summary
now**.

## Shared planning sheet (Google Sheets)
The Excel workbooks are rebuilt after every scan, so they are no place for the team's own notes. The shared planning
sheet is: a Google spreadsheet in your Drive that the AI assistant's Google connector keeps up to date every morning,
while the team's own columns stay exactly as the team left them. Setting it up takes about 5 minutes and uses the
connector set up under *AI assistant* above (no API key and no e-mail settings are needed for it).

1. Open <https://script.google.com> and your project *Geotechnical News Desk assistant*.
2. Replace the code with the current [`assistant/bridge.gs`](assistant/bridge.gs) (on GitHub, open the file and press the
   copy icon) and put your link to the key document back on line 15 (or keep the key in the Script property
   `ANTHROPIC_API_KEY`). Press **Save**.
3. Choose **setupPlanningSheet** in the function menu at the top and press **Run**. Google asks for new permissions:
   press **Review permissions**, choose your account, then **Advanced → Go to project** and **Allow**. The script may
   now see, edit and create your spreadsheets (the planning sheet), connect to an external service (to read the
   website's data) and run when you are not present (the daily update).
4. The log at the bottom shows `Planning sheet: https://docs.google.com/spreadsheets/d/…`. Open that address: the sheet
   *Geotechnical News Desk — planning* is in your Drive.
5. Share it with the team: in the sheet, press **Share** (top right), add the team's addresses as **Editors** and press
   **Send**. Leave *General access* on *Restricted*, so only the people you add can open it.
6. *Optional:* paste the address into `config.yaml` under `planning:` → `sheet_url:`. The issue pages then show a
   **Shared planning sheet (Google Sheets)** button (only the people you shared it with can open it).

No new deployment is needed: the daily update runs the saved script, and the assistant and the e-mails work as before.

**How the daily update works.** Every morning at about 07:00 Cairo time (after the 05:00 scan) the connector reads the
website's data for the two newest issue windows (the current quarter and the one before) and the suggested issue layout.
* **"Q4 2026 stories"** (one tab per quarter) lists every story and research paper of the quarter: Status (dropdown: To
  review, Shortlisted, Commissioned, Published, Not used), Assigned to, Editor notes, then the date, theme, rating,
  suggested use, the headline linked to the article (Claude's English translation marked *(translated)*, with the original
  headline beside it), the magazine angle, *Check with*, the source, the country and place, the developing story and
  whether it is a story or a paper. New stories are added **at the bottom, the best rated first** (use the filter buttons
  in the header row to sort). The news desk's columns are refreshed each morning; **Status, Assigned to and Editor notes,
  and any column you add, are never overwritten**. A story that is no longer in the digest stays, marked in *Digest note*.
  Do not delete rows: set the Status to *Not used* (a deleted row comes back the next morning).
* **"Q4 2026 plan"** follows the suggested issue layout: a row for each slot of the sections the scanner fills, where the
  proposed story is picked from a dropdown of the quarter's stories marked *Shortlisted* (or *Commissioned* or
  *Published*), and a row for each society or editor contribution, with the contact, Assigned to, Status (To do,
  Requested, Draft received, Edited, Ready, Dropped) and Notes. The dropdown is refreshed with the morning update, so a
  story shortlisted today appears in it the next morning (or at once if you run **syncPlanningSheet** from the editor);
  until then, type or paste its headline. The plan is made once; later updates only refresh the dropdowns and add rows
  for sections added to the layout, and never change what the team has typed (a row you delete stays deleted; a renamed
  section gets new rows, so delete the old ones if you no longer need them). A plan tab you delete is made again from
  the layout the next morning.
* **How to use** (first tab) explains this and shows the time of the last update. The hidden *lists* tab holds the
  dropdown lists; leave it alone. **Do not rename the tabs:** the update finds them by name, so it would make a new tab
  under the old name and leave the renamed one as it was.
* As everywhere on the news desk, the sheet holds no publisher's text beyond the headlines: the angle and *Check with*
  are Claude's own words. Treat each story as a lead (*Before you use a story* is repeated on the first tab).

To update the sheet at once, run **syncPlanningSheet** from the editor. If an update cannot read the website, the log
says what failed and why, the tab of a quarter that could not be read is left as it was, and Google e-mails you a summary
of failed runs. Running **setupPlanningSheet** again is safe: it reuses the sheet (its ID is kept in the Script property
`SHEET_ID`, which may also hold the sheet's address) and never installs a second daily update. If that sheet cannot be
opened, it stops and says why instead of making a new one; to start a new planning sheet, delete the Script property
`SHEET_ID` and run **setupPlanningSheet**. To stop the daily update, open **Triggers** (clock icon on the left)
and delete it. If the website moves, set the Script property `SITE_URL` to its new address.

## Changing things
* **Sources, searches, keywords, themes, limits:** all in `config.yaml` (edit it on GitHub with the pencil icon).
  Adding a language is one line under `extra_queries`. The world map (`map:`), developing stories (`storylines:`), events
  calendar (`events:`) and e-mail (`alerts:`) have their own sections at the end, each explained in its comments.
* **Issue layout and planning sheet:** `issue_layout:` and `planning:` in `config.yaml` (see *Suggested issue layout*
  and *Shared planning sheet*).
* **Events:** `data/events.yaml` (see *Events calendar*).
* **Schedule:** `.github/workflows/scan.yml` — daily at 05:00 Cairo time, adjusted automatically for Egypt's summer
  and winter clocks. GitHub sometimes starts scheduled runs late or skips them when it is busy, so two catch-up runs
  (mid-morning and midday Cairo time) scan only if the day has no digest yet. Changes to the website's design or
  `config.yaml` rebuild the site automatically (no scan).
* **Look of the website:** `assets/style.css` and `assets/app.js`. To rebuild the site without scanning, run `python site_builder.py`.

## Files
| File | Purpose |
|---|---|
| `scanner.py` | Reads the sources, scores and triages stories, saves the digest. |
| `site_builder.py` | Builds the website in `docs/` from the archive in `data/digests/`. |
| `exports.py` | Builds the Excel workbooks. |
| `report.py` | Builds the Word website report. |
| `brief.py` | Drafts the issue brief with Claude (`python brief.py --window 2026-Q4`, `--final`, `--auto`). |
| `geomap.py` | The World map page; locates archived stories that have no country yet. |
| `storylines.py` | Links follow-up reports to the earlier story (each scan) and builds the Developing stories page. |
| `events.py` | The events calendar: the Events page, the `.ics` feed and the weekly refresh (`python events.py --refresh`). |
| `notify.py` | Alerts and the weekly summary: sends the e-mails (`--auto`, `--weekly`, `--test`) and builds `docs/weekly/`. |
| `sync_data.py` | The workflows' save step: puts a run's data on the newest version of the site and rebuilds it. |
| `check_feeds.py` | Tests candidate feed addresses (run by the *Check feeds* workflow). |
| `data/briefs/` | The issue briefs (one file per issue window; the Word files are built from them). |
| `data/events.yaml` | The editors' list of events (edit it on GitHub; the format is explained at the top). |
| `data/events.json` | Events found by the weekly calendar refresh (written by `events.py`). |
| `data/notify.json` | The e-mails sent (alerts and weekly summaries), so none goes out twice. |
| `assistant/bridge.gs` | The AI assistant's connector, run in your Google account; it also sends the e-mails and keeps the shared planning sheet (see *AI assistant* and *Shared planning sheet*). |
| `data/changelog.yaml` | Change log and open items shown in the Word report. |
| `config.yaml` | All settings. |
| `assets/` | Website style sheet, scripts, icons and the world map outlines (`world.json`). |
| `tools/make_world.py` | Rebuilds `assets/world.json` from Natural Earth (only needed to change the map's outlines). |
| `.github/workflows/` | The daily scan (`scan.yml`), the issue brief (`brief.yml`), the events calendar, weekly summary and missing headline translations on demand (`extras.yml`) and Check feeds (`check-feeds.yml`). |
| `data/digests/` | **The permanent archive**, one file per day. |
| `data/seen.json` | Links the scanner has already read in the last 45 days, so the same article is not picked up twice. It only prevents repeats: nothing is removed from the archive, and the digests in `data/digests/` are kept permanently. |
| `docs/` | The generated website (do not edit by hand). |

## Notes
* Headlines link to the original publishers; the digest reproduces no article text, summary, abstract or image
  beyond the headline. Treat stories as leads and go to the primary source before publishing (see
  *Using the stories in the magazine (copyright)*).
* Some sites block automated readers or have no feed; Google News searches usually still catch their stories.
