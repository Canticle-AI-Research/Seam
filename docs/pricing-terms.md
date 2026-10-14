# SEAM Pricing — Terms & Conditions (draft)

Status: **founder draft, not legal advice.** Written in plain language on purpose
— "no fine print" is the point. Sections marked **[legal]** need a lawyer's
wording before publishing. Companion to [`docs/pricing-tiers.md`](pricing-tiers.md),
[`COMMERCIAL_LICENSE.md`](../COMMERCIAL_LICENSE.md), and [`NOTICE`](../NOTICE).

## 1. What these terms cover

**Current license:** Suite is proprietary under
[the personal license](../LICENSES/SEAM-Suite-Personal.txt): free personal,
noncommercial self-hosting; business and organizational use require a separate
written agreement. The proposed subscription prices below do not include or
grant a business license. Contact licensing@canticle.cc for those terms.

These draft terms describe proposed paid subscriptions, credits and the
Founder program. Current Suite use is governed by [LICENSE](../LICENSE),
[the personal license](../LICENSES/SEAM-Suite-Personal.txt) and its exact
implementation manifest. Personal, noncommercial self-hosting is free;
business use, including internal company operation and unpaid business
evaluation, needs a separate written agreement. Subscriptions do not expand
those rights. Suite has no automatic open-source conversion.

## 2. Plain-language definitions

- **Memory** — one stored record in your SEAM database.
- **Write** — creating one memory. Metered only when *we* do the processing
  ("managed write"). **1 write = 1 memory up to 1 KB**; a larger memory counts as
  one write per additional 1 KB (a 3 KB memory = 3 writes).
- **Managed write** — a write where SEAM performs the embedding + compile on our
  infrastructure. This is the only usage we bill for.
- **Recall / read** — retrieving or searching your memories. Never metered.
- **Credit** — the unit of managed-write billing. **1 credit = 1 managed write
  (up to 1 KB).**
- **BYO-key** — you supply your own model/API key, so the processing runs on your
  account. BYO-key usage is unlimited and never billed by us.
- **Self-host** — operating Suite on hardware or infrastructure you control.
  Personal, noncommercial use is free under the personal license. Business and
  organizational use require a separate written agreement.

## 3. Plans and prices

| Plan | Price | Included managed writes / month |
|---|---|---|
| Community | $0 | 1,000 taste + unlimited self-host/BYO |
| Solo | ~$5/mo | 5,000 |
| Pro | ~$15/mo | 25,000 |
| Max | ~$40/mo | 100,000 |
| Team | ~$20/seat/mo | 25,000 per seat (pooled) |
| Enterprise | Custom | Committed volume |

Annual billing = 2 months free. Prices are in USD and exclusive of any taxes
**[legal: tax handling]**. We may change list prices with notice (Section 10);
changes never apply retroactively to a billing period you've already paid.

## 4. What is unlimited, and what is metered

**Always unlimited, on every plan including Community and Founder:**

- **Recall / reads / search** — we never charge you to retrieve your own memory.
- **Storage** — memories are kept as long as you keep them. We do not charge
  storage rent and we do not auto-expire your memories.
- **Self-hosting and BYO-key** — genuinely uncapped, because the compute is yours.

**The only metered thing is managed writes** — the compute to turn your text into
memory on our infrastructure. Each plan includes a monthly allotment; usage past
it is billed as overage (Section 5). This is the only line item that scales with
use, and the only one whose pricing may change with market compute costs.

## 5. Managed writes, allotments, and overage

- Each plan includes the monthly managed-write allotment in Section 3.
- Allotments **reset monthly** and do **not** roll over (they're an included
  benefit, not purchased credits — see Section 6 for purchased credits, which do
  roll over).
- Past your allotment, overage is billed at **$1.00 per 1,000 managed writes**
  ($0.001/write), the same rate on every plan.
- You may keep writing past your allotment (overage bills automatically on
  postpaid, or draws from your prepaid balance) — you are not hard-blocked,
  subject to fair-use and rate limits (Section 8).
- Reads and storage are never counted toward any allotment.

## 6. Credits — prepaid and postpaid

You choose how to pay for managed usage:

- **Prepaid credits (wallet).** Buy credits up front. **Purchased credits roll
  over and do not expire monthly** while your account is active. Draw down as you
  write. Recommended default; no surprise bills.
- **Postpaid (metered).** We meter managed usage and bill in arrears at the end
  of each cycle. Available to Team and Enterprise; may require a payment method on
  file and is subject to credit approval **[legal]**.
- Your billing dashboard shows the **raw provider cost and our fee as separate
  line items.** Our fee on managed usage is a transparent handling fee (~12% on
  pass-through provider costs, or the published per-write rate for own-compute
  writes); we do not apply hidden markups.

## 7. Billing, renewal, cancellation, refunds

- **Renewal.** Subscriptions renew automatically each cycle until cancelled.
- **Cancellation.** You may cancel anytime, effective at the end of the current
  paid cycle. Cancellation is **one click** — no phone call, no retention maze.
- **Cancel-safe guarantee.** Subscription cancellation does not delete your
  data or change the personal-use permission for an authorized Suite copy.
  Business use remains governed by its separate written agreement. Hosted
  subscription conveniences may end according to their applicable terms.
- **Data export is always free**, on any plan and after cancellation.
- **Refunds.** Unused **prepaid credits** are refundable on request, minus credits
  already consumed **[legal: refund window + method]**. Subscription fees for the
  current period are non-refundable except where required by law, or under a
  stated satisfaction window **[legal]**.

## 8. Fair use and rate limits

"Unlimited" (recall, storage, self-host, BYO-key) and generous write allotments
are protected by ordinary anti-abuse rules:

- **Rate limits** apply per account (e.g. a maximum managed-write *rate* per
  minute) to protect shared capacity. These are flow limits, not monthly caps,
  and are set well above normal human or agent use.
- **Fair-use.** Automated, industrial-scale, or reselling-style usage that is
  clearly outside individual or team use may be rate-limited or asked to move to
  BYO-key or an Enterprise committed plan. We will contact you first, not cut you
  off silently **[legal]**.
- We do not throttle or silently downgrade quality as a billing tactic.

## 9. Bring-your-own-key and third-party providers

- When you use BYO-key, your use of that third-party model provider is governed by
  **their** terms, and their costs are billed by them, not us.
- When you use managed writes/inference, we run the processing; underlying model
  providers may change their prices, which may affect our managed pricing on a
  going-forward basis (Section 10). Your recall, storage, and self-host terms are
  unaffected.

## 10. Price changes

- We may change list prices or the managed-write overage rate with **at least 30
  days' notice** **[legal: notice period]**.
- Changes are **never retroactive** to a period you've already paid.
- **Founder Pass price-lock** (Section 11) overrides list-price increases for pass
  holders.
- Managed writes are the only component whose price may track market compute
  costs; personal self-host/BYO remains subject to the personal license, and
  business self-hosting remains subject to its separate agreement.

## 11. Founder program

A two-layer launch program. Founder status is tied to your account and is
non-transferable **[legal]**.

**Layer 1 — First 100: MVP for Life (free).**
- The first 100 accounts to claim it receive **founder status free for life**.
- Includes the convenience layer (login, encrypted backup, sync, remote plane,
  auto-managed lever-packs), unlimited recall + storage, a **fixed capped monthly
  write allotment** (Pro-level, ~25,000 — *not* unlimited; overage billed
  normally), and founder perks (badge, roadmap input).
- Closes permanently once 100 are claimed.

**Layer 2 — Next 1,000: MVP Founder Pass (paid).**
- A **one-time purchase (~$49)**, hard-capped at **1,000 seats**, then closed for
  good.
- Grants, **for life**: **30% off any subscription tier**, **25% off overage
  credits**, a **price-lock** (never pay more than founder rates), and founder
  perks.
- The Founder Pass is a discount on future subscriptions; it is **not** itself a
  subscription and does not include managed writes on its own.

**What "for life" means.** For as long as SEAM operates the paid service and your
account remains active and in good standing. It does not obligate SEAM to operate
any service indefinitely, and it does not survive account termination for abuse or
non-payment of other charges **[legal: this clause needs real wording]**.

**Refunds on the Founder Pass** — refundable within a stated window if unused
**[legal]**; after founder benefits have been applied, it is non-refundable.

## 12. Suite license and self-hosting

- Suite is proprietary with free personal, noncommercial self-hosting under
  [the personal license](../LICENSES/SEAM-Suite-Personal.txt) for the exact
  [manifest files](../LICENSES/SEAM-Suite-manifest.json).
- Business, employment, client and organizational use, including internal
  operation and unpaid business evaluation, require a separate written agreement.
- Embedded MIRL/HS/1 may operate the authorized Suite; independent reuse,
  source modification, redistribution and hosted/embedded offerings are reserved.
- The separate paid SDK is excluded. Subscription proposals do not grant its
  access or expand Suite rights. No automatic open-source conversion applies.
- Your own data remains yours. Applicable third-party and independently granted
  rights remain governed by their own terms.

## 13. Data ownership and privacy

- **Your memories are yours.** We claim no ownership of your stored content.
- **Hosted backup is end-to-end encrypted** — we store ciphertext and cannot read
  your memories **[legal: match to actual crypto implementation]**.
- We do not require telemetry or a phone-home for the core to function.
- Privacy specifics are governed by the SEAM Privacy Policy **[legal: link]**.

## 14. Service, availability, and disclaimers **[legal]**

- Paid hosted services are provided "as is" except where an Enterprise agreement
  states an SLA, warranty, or indemnity.
- Standard limitation-of-liability, warranty-disclaimer, indemnification, and
  dispute/governing-law clauses go here — to be drafted by counsel.

## 15. Changes to these terms

We may update these terms with notice. Material changes affecting paid plans take
effect at your next renewal, and Founder price-locks are honored regardless
**[legal]**.

---

### Open items to resolve before publishing

- Real legal drafting of every **[legal]** clause (liability, warranty,
  governing law, tax, refund windows, "for life" survivability).
- Final numbers: confirm prices, the $0.0002 cost basis behind allotments, the
  overage rate, the Founder Pass price and discount depth.
- Privacy Policy + confirmation that hosted backup is actually E2E-encrypted as
  stated.
