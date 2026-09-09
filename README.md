# Splitline Engine

The publishing and product machinery behind [Splitline](https://splitline.beehiiv.com) —
hybrid fitness, measured honestly.

It does three things on a schedule, without anyone opening a laptop:

1. **Crawls** the full public CrossFit Games Open leaderboard into a dataset it keeps.
2. **Writes** a data-led post each week — real analysis, real charts, real numbers —
   and refuses to publish when the data has nothing to say.
3. **Rebuilds** the paid product from the same dataset, so it is never out of date.

## Why the numbers can be trusted

The prose is templated; the findings are not. Every figure in a post is
interpolated from a value computed at run time, so no sentence can claim
something the data does not show. Before anything is delivered, the finding has
to clear a gate:

| Gate | Default | What it stops |
|---|---|---|
| `MIN_SAMPLE` | 500 | Stories about a handful of athletes |
| `MIN_EFFECT` | 0.08 | Stories about noise |

If nothing clears, the run exits `2`, the workflow logs a warning, and no post
goes out. A quiet week is a feature. It is the difference between an automated
newsletter and an automated slop generator.

## Two sports, one engine

HYROX is the in-season sport — races run most weekends from September — and
the Open runs once a year in February. The engine handles both through the
same gate, renderer and delivery; only the source and the story bank differ.

| | HYROX | CrossFit Open |
|---|---|---|
| Source | `sources/hyrox.py` (HTML, one request per athlete) | `sources/crossfit.py` (JSON API) |
| Angles | `analysis/hyrox_angles.py` | `analysis/angles.py` |
| Runner | `scripts/run_hyrox.py` | `scripts/run_weekly.py` |
| Product | `product/pacing.py` — HYROX Pacing Plan | `product/workbook.py` — Open Benchmark Workbook |
| Sales page | `site/hyrox.html` | `site/index.html` |

```bash
python scripts/ingest_hyrox.py --season 8 --event H_LR3MS4JI13EE --sample 400
python scripts/build_pacing.py --men data/..._men_raw.txt \
    --women data/..._women_raw.txt --race "2026 HYROX Beijing"
python scripts/run_hyrox.py --men ... --women ... --race "..." --dry-run
```

## The story bank

Angles run in order; each is used once, then the bank cycles.

| Slug | Question it asks |
|---|---|
| `age-curve` | Where does the Open actually peak, and which workout punishes age hardest? |
| `body-signature` | Which workouts favour a body type, and by how much? |
| `home-judge` | Do athletes validated at their own gym score differently? |
| `affiliate-effect` | Do bigger gyms produce better athletes? |
| `attrition` | Who quits the Open, and what predicts it? |
| `spike-vs-floor` | Do top finishers win on peaks or on the absence of holes? |
| `cutlines` | What did every percentile threshold actually cost? |
| `geography` | Which countries have the deepest fields, measured at the median? |

HYROX angles (`analysis/hyrox_angles.py`):

| Slug | Question it asks |
|---|---|
| `sex-shape` | At the same finish time, where do men and women actually differ? |
| `where-won` | Which segment explains most of the fast-to-slow gap? |
| `run-fade` | How much does the last kilometre slow down, and for whom? |

Adding a new one is a single function in `splitline/analysis/angles.py`
decorated with `@angle("slug")`, returning a `Finding`. Nothing else changes.

## Layout

```
splitline/
  config.py            all tuning, all env vars
  style.py             brand palette, matplotlib theme, inlined email CSS
  store.py             dataset cache (parquet, or gzipped CSV without pyarrow)
  sources/crossfit.py  the leaderboard crawler
  analysis/
    finding.py         the unit of output, and the publish gate
    angles.py          the story bank
  render/
    charts.py          chart builders
    post.py            beehiiv-safe HTML with every style inlined
  deliver/
    beehiiv.py         Create Post API (needs a Max plan)
    email_smtp.py      ready-to-publish email (works on any plan)
  product/
    workbook.py        the paid Benchmark Workbook
scripts/
  ingest.py            crawl the leaderboard
  run_weekly.py        the weekly run — this is what cron calls
  build_product.py     rebuild the product
  make_fixture.py      synthetic data for testing, never for publishing
```

## Running it by hand

```bash
pip install -r requirements.txt

python scripts/ingest.py --probe          # field size, one request
python scripts/ingest.py --max-pages 5    # cheap smoke test
python scripts/ingest.py                  # full crawl (~30 min)

python scripts/run_weekly.py --dry-run    # render without delivering
python scripts/run_weekly.py --angle attrition --dry-run
python scripts/build_product.py
```

To develop without touching the leaderboard:

```bash
python scripts/make_fixture.py --n 40000
python scripts/run_weekly.py --dry-run
```

The fixture writes a `.SYNTHETIC` marker beside the dataset. `build_product.py`
refuses to package anything while that marker exists unless you pass
`--allow-preview`, and a preview build is stamped in its filename. Synthetic
data cannot reach a customer by accident.

## Delivery

The pipeline always writes the post to `posts/<date>/<slug>/` first —
`email.html`, `preview.html`, `post.json`, and the charts. Delivery is
best-effort on top of that, and the run summary says honestly where the post
ended up.

- **beehiiv API** — set `BEEHIIV_AUTOPOST=true`. The Create Post endpoint needs
  a **Max or Enterprise** plan; on anything lower it returns 403 and the run
  falls back cleanly.
- **Email** — set the SMTP secrets and the finished post lands in your inbox,
  rendered, with the HTML attached. Publishing is paste and send.

## Configuration

Repository **variables** (not secret):

| Name | Default | Notes |
|---|---|---|
| `CF_YEAR` | `2026` | Open season to analyse |
| `CF_DIVISIONS` | `1,2` | `1` Men, `2` Women; masters are 3–14 |
| `ASSET_BASE` | — | Public https base for chart images. Required for email images to load. |
| `SPLITLINE_PRODUCT_URL` | — | Adds the product CTA to every post |
| `BEEHIIV_AUTOPOST` | `false` | Only turn on with a Max plan |

Repository **secrets**:

`BEEHIIV_API_KEY`, `BEEHIIV_PUB_ID`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`,
`SMTP_PASS`, `NOTIFY_EMAIL`.

`ASSET_BASE` must be reachable without authentication, because email clients
fetch the images anonymously. Two options that work:

- Public repo: `https://raw.githubusercontent.com/<you>/splitline-engine/main/posts`
- Netlify: deploy `posts/` and point `ASSET_BASE` at your own domain (better —
  the images then carry your brand, and you keep the referrer data).

## Method and corrections

Percentiles are computed over **finishers** — athletes with a valid score on
every workout — not over everyone who registered. Including non-finishers
flatters the whole field by roughly fifteen points and is the single most
common error in leaderboard analysis.

Height and weight are self-reported and frequently blank, so body-composition
findings cover a subset of the field and say so in the copy.

Corrections are published, not quietly patched.
