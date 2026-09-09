# Setup — everything you have to do, in order

Total hands-on time: about 40 minutes. After that the engine runs itself.

Nothing below needs code. Steps 1–4 get the newsletter publishing itself
weekly. Steps 5–7 turn on the money.

---

## 1. Put the repo on GitHub — 5 min

Make it **public**. Three reasons, in order of importance:

1. Your tagline is *"analysis, uncertainty and code included."* A public repo is
   that promise kept, and it is a real differentiator in a niche full of
   unsourced claims.
2. Chart images in your emails need a public URL. A public repo gives you one
   for free.
3. GitHub Actions minutes are unlimited on public repos. Private, you would burn
   through the free tier on the monthly crawl alone.

Nothing secret lives in the code — every credential is a GitHub secret.

```bash
cd splitline-engine
git init && git add . && git commit -m "Splitline engine"
gh repo create splitline-engine --public --source=. --push
```

## 2. Set the repository variables — 3 min

**Settings → Secrets and variables → Actions → Variables**

| Name | Value |
|---|---|
| `CF_YEAR` | `2026` |
| `CF_DIVISIONS` | `1,2` |
| `ASSET_BASE` | `https://raw.githubusercontent.com/LorcanE/splitline-engine/main/posts` |

## 3. Set the secrets so the post reaches you — 5 min

**Settings → Secrets and variables → Actions → Secrets**

| Name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the Gmail address the post should be sent **from** |
| `SMTP_PASS` | a Gmail **app password**, not your account password |
| `NOTIFY_EMAIL` | the address the post should be sent **to** |
| `BEEHIIV_PUB_ID` | from beehiiv → Settings → Publication (only needed for API auto-publish) |

Gmail app password: Google Account → Security → 2-Step Verification → App
passwords. Takes two minutes and avoids putting your real password anywhere.

## 4. Do the first crawl — 30 min, unattended

**Actions → Refresh dataset and rebuild product → Run workflow.**

It probes the field first and prints the size, then crawls, then commits the
dataset and builds the product. Watch the first one; you never need to again.

Then **Actions → Weekly post → Run workflow** to produce a post immediately.
It arrives in your inbox, rendered, with the HTML attached. Paste it into a new
beehiiv post and send. From then on it fires every Monday morning by itself.

> If a week ever produces nothing, that is deliberate. The run refuses to
> publish a finding that does not clear its sample and effect thresholds. The
> job summary tells you what each angle scored.

---

## 5. List the product on Lemon Squeezy — 15 min

Store: `splitlinehq.lemonsqueezy.com`.

**Launch with the HYROX Pacing Plan, not the Open workbook.** HYROX races run
most weekends from September; the Open is in February. Both products are
finished — the Open workbook is simply out of season until January, and will
be worth more then than it is now.

- **Name:** Splitline HYROX Pacing Plan
- **Price:** $19. A pre-race impulse buy for an athlete, not a business tool.
- **Delivery:** upload the `.xlsx` as the digital download. Lemon Squeezy is
  Merchant of Record, so it collects and remits VAT/GST worldwide for you.
  That is the genuinely passive part.
- **Licence line:** one athlete, or one coaching staff.

Build the file with:

```bash
python scripts/build_pacing.py \
    --men data/hyrox_beijing_men_raw.txt \
    --women data/hyrox_beijing_women_raw.txt \
    --race "2026 HYROX Beijing"
```

It lands in `dist/`, which is gitignored on purpose — the repo is public and
the product is not.

Then set the `SPLITLINE_PRODUCT_URL` repository **variable** to the checkout
link. Every future post gets a buy button in the footer automatically. That is
the whole funnel: free tools capture the email, the weekly post proves the
analysis is real, the footer sells the workbook.

## 6. Put the sales page up — 10 min

`site/hyrox.html` is the HYROX sales page (`site/index.html` is the Open one,
for January). Drag the `site` folder onto Netlify, then replace
`REPLACE_WITH_LEMONSQUEEZY_CHECKOUT_URL` in the page with your real checkout
link, and link it from the free tools you already have live.

## 7. Optional: full auto-publish — 2 min

If you ever move to a beehiiv **Max** plan, set the `BEEHIIV_API_KEY` secret and
the `BEEHIIV_AUTOPOST` variable to `true`. The post is then created directly in
beehiiv as a draft and you stop pasting. Leave `BEEHIIV_STATUS` at `draft`
until you have watched a few land — flipping it to `confirmed` publishes and
sends without a human, which is a decision worth making deliberately.

---

## What runs when

| Schedule | Workflow | What happens |
|---|---|---|
| Mondays 07:00 Melbourne | Weekly post | Picks the next angle, analyses, writes, charts, emails you |
| 1st of the month, 04:00 | Refresh dataset | Full re-crawl, rebuilds the product as a private workflow artifact |
| Every push | Self test | 82 checks, plus a live probe of the leaderboard API |

## When something breaks

The leaderboard is someone else's API and it will change eventually. The `smoke`
job in CI probes it on every push, so you will find out from a red tick rather
than from a silent Monday.

If the crawler's field names drift, `splitline/sources/crossfit.py` has the
verified contract written at the top of the file — that comment is what to
compare against.
