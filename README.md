# Geotechnical News Scanner — ISSMGE Magazine

Every morning GitHub automatically:
1. reads 26 websites (societies, hazard agencies, trade press) and 76 Google News
   searches listed in `config.yaml`. The searches cover seven English-language
   editions (UK, US, India, Australia, South Africa, Singapore, UAE) plus Arabic,
   French, Spanish, Portuguese, German, Italian, Turkish, Hindi, Indonesian,
   Chinese and Japanese, so coverage is worldwide;
2. scores each new story for geotechnical relevance (keywords) and removes duplicates;
3. *(optional)* asks Claude to rate each story 1–5, place it under one of the magazine's
   eight cross-cutting themes, suggest a use (news brief, feature lead, Academia-to-Industry
   topic…), write the geotechnical angle, and translate non-English headlines;
4. publishes the digest at `https://<your-username>.github.io/<repo-name>/`
   (with an archive) and *(optional)* e-mails it to you.

Stories already shown are remembered, so each digest contains only new items.

## Quick setup — one command (recommended)

Install the free GitHub CLI (https://cli.github.com), then run once:

    gh auth login          # opens your browser; credentials stay on your computer

Then, from inside this folder:

    bash setup.sh          # or: bash setup.sh my-repo-name

The script creates the repository, uploads the files, enables write permissions and
the Pages website, asks for your Claude API key (typed hidden, stored as an encrypted
GitHub secret), optionally sets up e-mail, and starts the first scan.

---

## Manual setup (about 15 minutes, once)

1. **Create a repository** on GitHub, e.g. `geotech-news`, and upload all these files,
   keeping the folders (`.github/workflows/scan.yml`, `data/`, `docs/`).
   *Tip:* the `.github` folder is hidden on some computers. If it doesn't upload, create the file
   on GitHub via **Add file → Create new file**, name it `.github/workflows/scan.yml`
   and paste the contents.
2. **Allow the workflow to save results:** Settings → Actions → General →
   *Workflow permissions* → **Read and write permissions** → Save.
3. **Turn on the web page:** Settings → Pages → *Deploy from a branch* → branch `main`,
   folder `/docs` → Save. (Free for public repositories.)
4. **Run a first scan:** Actions tab → *Geotechnical news scan* → **Run workflow**.
   After 1–2 minutes, open your Pages address.
5. **Check "Scanner notes and sources that failed"** at the bottom of the digest. For any
   failed site, find its RSS feed address (often `site.com/feed/` or an RSS icon) and
   replace the address in `config.yaml`.

## Optional: AI triage with Claude
Get an API key at console.anthropic.com (billed separately from a Claude.ai subscription).
Then Settings → Secrets and variables → Actions → **New repository secret**:
`ANTHROPIC_API_KEY`. The configured model is Claude Haiku, the lowest-cost model.
Without a key the tool still works using keywords only.

## Optional: e-mail delivery
Add these secrets: `SMTP_HOST`, `SMTP_PORT` (usually 587), `SMTP_USER`, `SMTP_PASSWORD`,
`MAIL_TO` (comma-separate several addresses).
For Gmail: host `smtp.gmail.com`, and create an *App password* in your Google account
(2-step verification required) to use as `SMTP_PASSWORD`.

## Changing things
All in `config.yaml`: add sites under `feeds`, add Google News searches under `queries`
(e.g. Arabic or French searches with `language: ar`), tune keyword weights, or change
`lookback_hours`/`max_items`. The schedule is in `.github/workflows/scan.yml`.

## Sources at a glance
* **Geotechnical specialists:** GeoEngineer, Geosynthetica, The Landslide Blog (Eos).
* **Societies and institutions:** ISSMGE, ASCE Geo-Institute, DFI, ICE, FHWA.
* **Hazard and post-event reporting:** GEER Association, USGS Landslide Hazards,
  USGS news, ReliefWeb.
* **Trade press:** New Civil Engineer, Tunnels & Tunnelling, TunnelTalk, Rail Business UK,
  Railway Gazette, Rail Technology Magazine, World Highways, International Construction,
  Construction Enquirer, ENR, Construction Week Middle East, Mining.com.
* **Research announcements:** ScienceDaily (Earth & Climate), Phys.org (Earth Sciences).

## Notes
* Headlines link to the original publishers; the digest reproduces no article text beyond
  the short feed summary. Treat stories as leads and go to the primary source before publishing.
* Some sites block automated readers or have no feed; Google News searches usually still
  catch their stories.
