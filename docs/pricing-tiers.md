# SEAM Pricing Tiers

Status: draft / strategy. Prices are proposals — adjust freely. This document is
the full system: the tier ladder, the feature matrix, what "unlimited" honestly
means, and how every capability is sorted into **free**, **combine-with-self-host**,
or **hosted**.

Related boundary docs: [`COMMERCIAL_LICENSE.md`](../COMMERCIAL_LICENSE.md),
[`docs/PROTECTION_MODEL.md`](PROTECTION_MODEL.md), [`NOTICE`](../NOTICE).

## The three rules the whole model obeys

1. **The subscription buys convenience and hosted infrastructure — never the
   ability to run SEAM.** Everything paid is reproducible with the open core +
   your own infra, and we document the DIY path.
2. **Charge for what costs *us* money (compute, storage, human time, legal
   liability). Give away what doesn't (the software itself).** This is why the
   price scales fairly with customer size — a solo dev consumes little and pays
   little; an enterprise consumes a lot and pays a lot.
3. **The core never loses a feature to create a paid tier.** Paid tiers only
   *add*. Cancelling is a non-event: your local node keeps running, your data
   stays yours.

## What "unlimited" honestly means here

The AI companies advertise "unlimited," then throttle you with hidden rate limits
and silently downgrade the model. We can do better, because of one structural
fact: **on the self-host path, you bring the compute.**

- **Unlimited stored memories** — it's your disk (self-host) or cheap text
  storage (hosted). MIRL records are tiny; this cap never realistically binds.
- **Unlimited retrieval / queries** — it's your CPU on self-host. We literally
  cannot meter your own machine.
- **Unlimited devices synced** — sync bandwidth is negligible.
- **Unlimited inference via bring-your-own-key** — your key, your tokens, no cap,
  at *every* tier including Free.

The only things with real per-use cost to us are the operations where **we front
the compute**: managed ingest (we run the embedding + MIRL compile) and managed
answer-generation (we run an LLM at query time). Those are the only two things we
meter — see "Usage & metering" below. Everything else — recall, search, storage,
and the entire self-host / BYO-key path — is genuinely unlimited, because it runs
on your compute or costs us effectively nothing.

## Usage & metering — "You pay to remember. Recall is free. Forever."

This is the heart of the model and the answer to "what do we charge usage for
that isn't tokens." We looked at how the field charges:

- **mem0** meters memories *stored* and retrieval *calls* (and paywalls graph) —
  it charges you to read, which we won't.
- **Zep** charges 1 credit per **350-byte Episode, on ingest only**; storage and
  retrieval are unmetered. Byte-based = provider-agnostic. This is the right idea.
- **Cognee** and **Hindsight** charge by **tokens** — exactly the unit you can't
  trust, because no two providers tokenize the same. Hindsight also charges
  storage rent and expires memories after 30 days.

SEAM's model takes the best of Zep and goes more generous:

**We charge only on the write side, by content size, in a provider-agnostic
unit. Everything on the read side is unlimited, and storage is free forever.**

The single metered axis is **managed writes** (ingest compute). Every paid tier
includes a **generous capped monthly write allotment**; past it, overage is
billed at a flat honest rate. Capping (rather than "unlimited") makes the model
**bankruptcy-proof by construction** — see the sizing rule below. Recall,
storage, and the self-host/BYO path stay unlimited on *every* tier because
metering them would cost the user for something that costs us nothing — the exact
greed move we refuse.

### Write pricing (illustrative — lock after measuring real compile COGS)

Unit: **1 write = 1 memory up to 1 KB** (a 3 KB document = 3 writes). Legible and
size-fair. Cost basis assumed here: **~$0.0002 per write** on cheap/open compute
(likely lower on our own open-model compute).

**Sizing rule (the profitability guarantee):** size each tier's free allotment so
that a user who *fully maxes it* is still profitable, and price overage at an
honest multiple of real cost. Then no subscriber can ever cost more than they pay
— a cohort of heavy users guarantees profit instead of risking bankruptcy.

| Tier | Price | Free writes / mo | Worst-case COGS if maxed | Margin at max |
|---|---|---|---|---|
| Community | $0 | 1,000 taste + unlimited self-host/BYO | $0.20 | funnel |
| Solo | $5 | 5,000 | $1.00 | 80% |
| Pro | $15 | 25,000 | $5.00 | 67% |
| Max | $40 | 100,000 | $20.00 | 50% |
| Team | $20/seat | 25,000 / seat (pooled) | $5 / seat | 75% |
| Enterprise | Custom | Committed | negotiated | — |

- **Overage: $1 per 1,000 writes** ($0.001/write = 5× cost) — flat everywhere,
  cheaper than Zep (~7×), transparent, profitable. Prepaid bundles roll over.
- Typical users touch <10% of their allotment → real-world margin ~95% and almost
  nobody ever pays overage, so it *feels* unlimited while staying capped for us.
- Allotments assume the $0.0002 cost basis; if real compile costs more, every
  allotment shrinks proportionally — the sizing rule holds regardless of the
  measured number. Own open-model compute keeps cost low and allotments generous.

- **The unit: 1 SEAM Credit = 1 KB of managed ingest.** Bytes, not tokens — no
  tokenizer disagreement, fully predictable, you can see the cost of a document
  before you send it. (Roughly 3× more generous per credit than Zep's 350-byte
  episode.)
- **Metered (the only things that cost us):**
  1. **Managed ingest** — when *we* embed + compile your memory. Priced per KB,
     always set above our worst-case COGS so we never lose money regardless of
     which model runs under the hood. We absorb token variance into a fixed
     per-KB margin.
  2. **Managed answer-generation** — when you ask *us* to run an LLM at query
     time to synthesize an answer. Drawn from managed-inference credits, or free
     with BYO-key.
- **Unlimited / free by construction (all tiers, including Community):**
  - **Unlimited recall / search / retrieval** — reads are cheap and, on
    self-host, your compute. We never meter a read.
  - **Unlimited storage, forever** — MIRL records are text; we don't charge rent
    and we never expire your memories (unlike Hindsight's 30-day decay).
  - **The entire self-host + BYO-key path** — genuinely uncapped, because you
    bring the compute. This is how SEAM is honestly one of the only "unlimited"
    memory products on the market.

Three headline "unlimited"s competitors can't cleanly match: **unlimited recall**
(mem0 caps it), **unlimited permanent storage** (Hindsight decays, mem0 caps
count), and **unlimited everything self-hosted**.

### Prepaid and postpaid — both, you choose

- **Prepaid credit wallet** — buy a bucket of SEAM Credits up front, they **roll
  over** (never expire monthly), draw down as you ingest. No bill shock. Default
  for individuals and plug-and-play. Top up anytime.
- **Postpaid metered** — we meter managed usage and bill at month end. For
  production/enterprise who can't risk running out mid-workload; pairs with
  committed-use discounts.
- A live dashboard shows raw provider cost and our fee as **separate line items**.
  Radical price transparency vs the opaque AI-token pricing everyone resents.

The result you asked for: **compute never costs you at a loss** (we only front
compute on metered, paid operations — self-host/BYO shifts it to the user), we
**bank** on managed ingest + inference + hosted + enterprise, and we can be
**genuinely generous with unlimited** everywhere the marginal cost is ~zero.

## The tier ladder

Mocking the AI-company ladder (Free / cheap / mid / high / org), but deliberately
cheaper and without the greed.

| | **Community** | **Solo** | **Pro** | **Max** | **Team** | **Enterprise** |
|---|---|---|---|---|---|---|
| **Price** | $0 | ~$5/mo | ~$15/mo | ~$40/mo | ~$20/seat/mo | Custom |
| **For** | Self-hosters | Effortless solo self-host | Power user | **The Unlimited tier** (no write meter) | Shared memory | Compliance & scale |
| **License** | BUSL-1.1 (self-host free) | + hosted conveniences | | | | + commercial terms |

Yearly = 2 months free. Community is not a trial and not a lite build — it is the
whole product.

### Founder program (launch) — two layers

**Layer 1 — First 100: MVP for Life (free). The gimmick.**
The first 100 users get founder status **free for life** — the headline hook that
creates launch buzz and 100 loud evangelists. Kept bankruptcy-safe by capping the
one thing that costs us:

- Convenience layer free for life — `seam login`, encrypted backup, cross-device
  sync, remote control plane, auto-managed lever-packs (all near-zero COGS).
- Unlimited recall + permanent storage (already free for everyone; locked in).
- A **fixed capped monthly write allotment** (e.g. Pro-level ~25k) — *not*
  unlimited. Max exposure ~$2/mo per user even if fully maxed (realistically
  cents); overage they buy like anyone. Cheap lifetime marketing, not an open tab.
- Founder badge + direct roadmap input.

Once 100 are claimed it closes forever — and "the first 100 got it free" is
exactly what sells Layer 2.

**Layer 2 — Everyone after: MVP Founder Pass (paid).**
Not a tier — a **one-time pass that modifies whatever tier you subscribe to**,
forever. A paid founder's membership that front-loads cash and rewards early
backers with permanent discounts.

- **Price:** one-time **~$49** (tunable) — pure upfront margin, before any COGS.
- **Availability:** a **hard cap of 1,000 founder seats** (not a time window) —
  concrete and easy to market ("1,000 founder seats, then gone"). Once claimed,
  it closes for good; that scarcity is what drives the buy-now.
- **Locks in for life:**
  - **30% off any subscription tier**, forever (founder pricing even as list
    prices rise)
  - **25% off overage credits**
  - **Price-lock** — never pay more than founder rates
  - **Founder perks** — badge, direct roadmap input, earliest access to new
    features and lever-packs

**Profitable and honest by construction.** The $49 is margin on day one. The
discount never drops price below cost, because base margins are 50–95%:

| Tier | List | −30% Founder | Worst-case COGS | Profit at max |
|---|---|---|---|---|
| Solo | $5 | $3.50 | $1.00 | +$2.50 |
| Pro | $15 | $10.50 | $5.00 | +$5.50 |
| Max | $40 | $28.00 | $20.00 | +$8.00 |
| Overage | $1/1k | $0.75/1k | $0.20/1k | 3.75× cost |

Guard: the founder discount stays below the margin floor, so even a fully-maxed
founder is still profitable. They *paid* for a real, permanent discount — no dark
pattern, no bait-and-switch.

## Feature matrix

Legend: ✓ = included · — = not included · numbers = that tier's allowance.

### Runtime & core — everything works on the free tier

| Feature | Community | Solo | Pro | Max | Team | Enterprise |
|---|---|---|---|---|---|---|
| Full local runtime (all retrieval signals, MIRL, provenance) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| All interfaces (CLI, shell, TUI, REST, MCP) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Self-improvement loop | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Lever-packs / tuned retrieval (manual pull) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Unlimited** stored memories | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Unlimited** local retrieval / queries | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Bring-your-own inference key (**unlimited**) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Community support (GitHub / Discord) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Free data export, always | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

### Convenience — wraps *your* self-hosted node (the reason to pay $5–40)

| Feature | Community | Solo | Pro | Max | Team | Enterprise |
|---|---|---|---|---|---|---|
| `seam login` — one-command wiring | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Encrypted hosted backup (E2E; we hold ciphertext) | — | 5 GB | 50 GB | **Unlimited\*** | Unlimited\* | Unlimited\* |
| Cross-device sync (unlimited devices) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Remote control plane (reach your dashboard anywhere) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Auto-managed lever-pack delivery + 1-click rollback | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Priority support (front of line) | — | — | ✓ | ✓ | ✓ | ✓ |

\* Fair-use. MIRL records are text — even heavy users rarely exceed tens of MB,
so this cap is generous by construction, not a trap.

### Managed usage — the only metered thing (real COGS)

Metered surface = managed ingest (per KB) + managed answer-generation. Priced in
SEAM Credits (1 credit = 1 KB managed ingest). See "Usage & metering" above.

| Feature | Community | Solo | Pro | Max | Team | Enterprise |
|---|---|---|---|---|---|---|
| BYO-key (always unlimited) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| **Unlimited recall / storage** (never metered, any tier) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Managed **writes** (ingest compute) | BYO-key | credit pool | credit pool | **Unlimited\*** | pooled | committed |
| Included monthly write credits | — | — | pool | **no meter** | pooled | committed |
| Buy-more credits — prepaid wallet (rollover) | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Postpaid metered billing | — | — | — | — | opt-in | ✓ |
| Transparent cost + labeled ~12% fee | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Solo stays BYO-key-first on purpose — a clean, high-margin, pure-software $5 sub
with zero token reselling. We never mark managed usage up opaquely; the fee is a
visible line item covering payment processing + ops. Postpaid is enterprise-side
(no bill-shock risk for individuals); prepaid rollover is the individual default.

### Team & organization

| Feature | Community | Solo | Pro | Max | Team | Enterprise |
|---|---|---|---|---|---|---|
| Shared memory spaces | — | — | — | — | ✓ | ✓ |
| Roles / RBAC | — | — | — | — | ✓ | ✓ |
| Tamper-evident audit log | — | — | — | — | ✓ | ✓ |
| Centralized billing | — | — | — | — | ✓ | ✓ |

### Enterprise — contracts, not features

| Feature | Community | Solo | Pro | Max | Team | Enterprise |
|---|---|---|---|---|---|---|
| SLA / warranty / indemnity | — | — | — | — | — | ✓ |
| Private connectors / custom integrations | — | — | — | — | — | ✓ |
| Air-gapped / on-prem deployment support | — | — | — | — | — | ✓ |
| Dedicated support + onboarding | — | — | — | — | — | ✓ |

## Fully-hosted SEAM (managed node) — optional add-on

For people who won't self-host at all: we run the node, same runtime. Priced by
usage (storage + inference), toggled on top of any paid tier. Highest margin when
run on open models on our own compute rather than reselling frontier tokens.

Kept deliberately *off* the main ladder so self-hosting stays the first-class
path and the funnel doesn't quietly drift cloud-ward.

## How each feature is sorted (free / combine-with-self-host / hosted)

This is the sorting logic behind the matrix, stated plainly for future features.

**Free (Community, BUSL-1.1) — "makes SEAM *work*":**
the entire runtime, every interface, unlimited memories/queries, BYO-key,
lever-packs, self-improvement loop, community support, free export. The product
is fully functional here forever. This is also the marketing engine.

Source-available, not Apache. Self-hosting — including internal commercial
production use at any scale — is free and always will be. The single
restriction is that you may not resell SEAM as a competing hosted service.
Each version becomes MPL-2.0 four years after it ships, so the promise is
enforceable rather than a matter of trust. This is what makes the ladder below
safe to build: the generosity is real, and the one thing it withholds is the
one thing that would destroy the business.

**Combine-with-self-host (Solo/Pro/Max) — "makes *your node* effortless":**
`seam login`, encrypted backup, cross-device sync, remote control plane,
auto-managed lever-pack delivery+rollback, priority support. You still run your
own node; the sub removes the chores and adds multi-device. This is the "empower
self-hosting" heart of the model — near-zero marginal cost, so high margin and
guilt-free.

**Hosted (we run compute) — "makes SEAM run *for* you":**
managed inference credits, fully-hosted node, hosted shared team spaces. Real
COGS, honest margin, priced by usage.

**Contracts (Enterprise) — "makes SEAM safe to adopt at scale":**
SLA, indemnity, connectors, on-prem support, onboarding. This is billed labor and
liability, which is why it's where the big checks are.

## Where the money actually is (so we don't fool ourselves)

- **Community** — free; it's the trust + funnel top, not revenue. Generosity is
  the growth strategy for the local-first crowd allergic to cloud lock-in.
- **Solo ($5)** — the on-ramp. Turns a self-hoster into a billing relationship
  and a habit. High margin, but never the profit center.
- **Pro / Max ($15 / $40)** — power-user recurring revenue, high margin.
- **Team ($20/seat)** — the recurring-revenue engine. 100 small teams ≈ $175k/yr.
- **Enterprise** — the big checks. Realistic memory-infra ACV $15–60k; ten deals
  = $150–600k/yr. This is "bank."
- **Hosted** — usage margin that scales with adoption, best on open models.

Generosity lives in Community + cancel-safety (nearly free to give). The money
lives in Team + Enterprise + Hosted (real cost, honest margin). Solo/Pro/Max are
the fair, cheap ladder that connects the two.

## Guardrails (the promises that keep it honest)

1. The core never loses a feature to create a paid tier — paid only adds.
2. Everything paid is reproducible with the open core + your own infra; we
   document the DIY path.
3. Cancel-safe: downgrading never disables your local node or holds your data.
4. Your memories stay yours — hosted backup is E2E encrypted (we hold
   ciphertext), export is always free.
5. No pay-to-use telemetry — the core never needs an account or phone-home.
6. Benchmarks stay free and honest — the harness is in the open core, never gated.
7. Managed inference is never marked up opaquely — cost + a visible fee.
8. "Unlimited" always means genuinely uncapped or a published number — no silent
   throttle, no silent model downgrade.

## Decided

- **Unlimited stays** — SEAM aims to be one of the only "unlimited" memory
  products, made honest by charging on the write, unlimited on the read.
- **Usage unit = SEAM Credit = 1 KB managed ingest** (bytes, provider-agnostic,
  not tokens). Recall/storage never metered.
- **Both prepaid (rollover wallet) and postpaid (metered)** — individuals prepay,
  enterprise postpays.
- **Founder program, two layers** — (1) **first 100 = MVP for Life free** (the
  gimmick; capped write allotment keeps it bankruptcy-safe), then (2) **paid MVP
  Founder Pass** (~$49) for a permanent 30%-off-for-life discount + perks, capped
  at the **next 1,000 seats** (hard cap, not a time window). Layer 1's buzz sells
  Layer 2; both front-load cash and stay profitable.
- **Subscription is "half and half"** — plug-and-play convenience (Solo/Pro/Max)
  + production-grade (Team/Enterprise). Convenience-and-scale payers fund the
  generosity for everyone else.

## Still open

- **Credit price + tier allotments** — the per-KB credit price and each tier's
  included monthly pool are placeholders; set them once we measure real managed
  ingest COGS (must price ≥ ~3–5× worst-case cost).
- **Max fair-use ceiling** — the published soft cap on Max managed usage.
- **Prices** — $5 / $15 / $40 deliberately undercut the $20 / $200 AI ladder. Too
  cheap to signal quality, or correct as the anti-greed positioning?
- **Team vs Enterprise focus first** — Team-first (multi-seat/RBAC/shared-spaces)
  or Enterprise-first (compliance + connectors + sales motion)? Different
  near-term roadmaps.
