# Three-minute audit walkthrough

Run `python -m audit_env.demo` inside the prepared offline Linux image. It uses
the same environment, isolated tool channel, matcher and common reward in all
three cases. It writes delivery captures and separate private results.

**0:00–0:40 — Source event and mutation.** In hand-authored `company-b`, invoice
`inv-264` is for 10,000,000 KZT minor units. Payment `pay-627` explicitly directs
7,000,000 to it. The clean books apply all 7,000,000, leaving a legitimate
3,000,000 outstanding. The causal mutation changes the two application posting
legs to 5,000,000. A 2,000,000 allocation discrepancy is distinct from the
legitimate outstanding balance. See fixture private provenance on the trusted
side, and the invoice/payment/ledger on the public side.

**0:40–1:30 — Visible proof.** Reconciliation reads invoices, payments and ledger,
then the payment document. `doc-492` establishes the intended allocation and
`settlement:pay-627` establishes the applied amount. These accessible records
support the affected pair `{pay-627, inv-264}`, currency KZT and discrepancy
`7,000,000 - 5,000,000 = 2,000,000`. Private truth is not given to this policy.

**1:30–2:00 — Submit, match, score.** The supported claim matches one truth issue
with its complete proof: TP=1, FP=FN=0. Four inspections plus submit yield
`2*1 - 1 - .002*4 = .992`. The public terminal reward remains zero in closed
mode; .992 appears only in the trusted result.

**2:00–2:40 — Clean and accusation controls.** The same public-data reconciler
returns no findings on `company-a`: F1=1, four inspections, return .992. A separate
jailed demonstration policy reads one invoice and submits one unsupported
duplicate accusation against the same clean company. Its envelope is valid;
the matcher assigns TP=0, FP=1, FN=0, F1=0 and clipped return -1. The case is a
false accusation, not a malformed-submit shortcut.

**2:40–3:00 — What oracle means.** The evaluator-only oracle gets complete truth
and proof and can submit in one action, return 1. It establishes attainable
scoring for correct supported answers. It demonstrates neither ordinary-agent
reasoning nor model training. Open the saved trajectories and private results
in `evaluator/stage12/demo/` to inspect all three cases.
