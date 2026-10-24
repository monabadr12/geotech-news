#!/usr/bin/env bash
# =====================================================================
#  One-command setup for the Geotechnical News Scanner.
#
#  Needs the free GitHub CLI:  https://cli.github.com
#  Then, once:                 gh auth login
#
#  Usage (from inside this folder):
#      bash setup.sh                 # repo name defaults to geotech-news
#      bash setup.sh my-repo-name
# =====================================================================
set -euo pipefail

REPO="${1:-geotech-news}"

say() { printf "\n\033[1m==> %s\033[0m\n" "$1"; }

# ---------------------------------------------------------------- checks
command -v git >/dev/null || { echo "git is not installed. Install it from https://git-scm.com"; exit 1; }
command -v gh  >/dev/null || { echo "The GitHub CLI is not installed. Install it from https://cli.github.com"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "You are not logged in to GitHub. Run:  gh auth login"; exit 1; }
[ -f scanner.py ] || { echo "Run this script from inside the folder that contains scanner.py."; exit 1; }

OWNER="$(gh api user --jq .login)"
say "Setting up $OWNER/$REPO"

# ---------------------------------------------------------------- repo + push
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "Repository already exists — pushing the current files to it."
  git init -q 2>/dev/null || true
  git remote remove origin 2>/dev/null || true
  git remote add origin "https://github.com/$OWNER/$REPO.git"
else
  git init -q
  gh repo create "$REPO" --public --description "Daily geotechnical news digest for the ISSMGE magazine" >/dev/null
  git remote add origin "https://github.com/$OWNER/$REPO.git"
fi

git add -A
git -c user.name="setup" -c user.email="setup@local" commit -qm "Geotechnical news scanner" || echo "Nothing new to commit."
git branch -M main
git push -u origin main   # never --force: it would erase the digest archive
say "Files uploaded"

# ---------------------------------------------------------------- permissions
gh api -X PUT "repos/$OWNER/$REPO/actions/permissions/workflow" \
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=false >/dev/null
say "Workflow given permission to save each digest"

# ---------------------------------------------------------------- Pages site
if gh api "repos/$OWNER/$REPO/pages" >/dev/null 2>&1; then
  gh api -X PUT "repos/$OWNER/$REPO/pages" --input - >/dev/null <<'JSON' || true
{"source":{"branch":"main","path":"/docs"}}
JSON
else
  gh api -X POST "repos/$OWNER/$REPO/pages" --input - >/dev/null <<'JSON' || true
{"source":{"branch":"main","path":"/docs"}}
JSON
fi
say "Website enabled: https://$OWNER.github.io/$REPO/"

# ---------------------------------------------------------------- secrets
echo
echo "Claude API key (optional but recommended — it enables the AI rating,"
echo "the magazine angle, and translation of foreign headlines)."
echo "Paste it and press Enter, or just press Enter to skip. It is NOT shown on screen."
read -r -s -p "ANTHROPIC_API_KEY: " KEY; echo
if [ -n "${KEY:-}" ]; then
  printf '%s' "$KEY" | gh secret set ANTHROPIC_API_KEY --repo "$OWNER/$REPO"
  say "API key stored as an encrypted GitHub secret"
else
  echo "Skipped — the scanner will rank stories by keywords only."
fi

echo
read -r -p "Set up e-mail delivery of the digest as well? [y/N] " WANT_MAIL
if [[ "${WANT_MAIL:-N}" =~ ^[Yy]$ ]]; then
  read -r -p "SMTP host (e.g. smtp.gmail.com): " SMTP_HOST
  read -r -p "SMTP port [587]: " SMTP_PORT; SMTP_PORT="${SMTP_PORT:-587}"
  read -r -p "SMTP user (your e-mail address): " SMTP_USER
  read -r -s -p "SMTP password / app password: " SMTP_PASSWORD; echo
  read -r -p "Send digests to (comma-separated): " MAIL_TO
  for pair in "SMTP_HOST=$SMTP_HOST" "SMTP_PORT=$SMTP_PORT" "SMTP_USER=$SMTP_USER" \
              "SMTP_PASSWORD=$SMTP_PASSWORD" "MAIL_TO=$MAIL_TO"; do
    printf '%s' "${pair#*=}" | gh secret set "${pair%%=*}" --repo "$OWNER/$REPO"
  done
  say "E-mail settings stored as encrypted secrets"
fi

# ---------------------------------------------------------------- first run
say "Starting the first scan"
sleep 5
gh workflow run "Geotechnical news scan" --repo "$OWNER/$REPO" || \
  echo "Could not start it automatically — open the Actions tab and press 'Run workflow'."

cat <<EOF

--------------------------------------------------------------------
 Done. What happens next:

  * The scan takes 2-4 minutes. Watch it with:
        gh run watch --repo $OWNER/$REPO
    or on github.com/$OWNER/$REPO/actions

  * Your digest will appear at:
        https://$OWNER.github.io/$REPO/
    (the very first Pages build can take a few extra minutes)

  * It will then run by itself every day at 05:00 UTC.
    To change that, edit .github/workflows/scan.yml

  * Check "Sources that failed" at the bottom of the digest and fix
    those addresses in config.yaml.
--------------------------------------------------------------------
EOF
