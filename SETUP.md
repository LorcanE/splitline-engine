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
| `ASSET_BASE` | `https://raw.githubusercontent.com/YOURNAME/splitline-engine/main/posts` |

## 3. Set the secrets so the post reaches you — 5 min

**Settings → Secrets and variables → Actions → Secrets**

| Name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | `splitlinehq@gmail.com` |
| `SMTP_PASS` | a Gmail **app password**, not your account password |
| `NOTIFY_EMAIL` | `splitlinehq@gmail.com` |
| `BEEHIIV_PUB_ID` | `pub_385f736e-c99e-4e63-80ad-46fa8a31d552` |

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

The workbook is built and waiting in `dist/`, and republished as a GitHub
release every month.

- **Name:** Splitline Open Benchmark Workbook 2026
- **Price:** $39. It is a business tool for gym owners, not an athlete impulse
  buy. Do not price it at $9 — you will get fewer sales, not more, because $9
  signals a PDF.
- **Delivery:** upload the `.xlsx` as the digital download. Lemon Squeezy
  handles payment, VAT, invoicing and delivery. That is the passive part.
- **Licence line:** one gym, one coaching staff.

Then set the `SPLITLINE_PRODUCT_URL` repository **variable** to the checkout
link. Every future post gets a buy button in the footer automatically. That is
the whole funnel: free tools capture the email, the weekly post proves the
analysis is real, the footer sells the workbook.

## 6. Put the sales page up — 10 min

`site/index.html` is a complete, self-contained landing page. Drag the `site`
folder onto Netlify, point the Lemon Squeezy checkout button at your product,
and link it from the free tools you already have live.

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
| 1st of the month, 04:00 | Refresh dataset | Full re-crawl, rebuilds the product, cuts a release |
| Every push | Self test | 51 checks, plus a live probe of the leaderboard API |

## When something breaks

The leaderboard is someone else's API and it will change eventually. The `smoke`
job in CI probes it on every push, so you will find out from a red tick rather
than from a silent Monday.

If the crawler's field names drift, `splitline/sources/crossfit.py` has the
verified contract written at the top of the file — that comment is what to
compare against.
