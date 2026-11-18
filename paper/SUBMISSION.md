# Submission notes (2026-11-18)

Build everything with `paper/package.sh` (needs `brew install tectonic`). Outputs land in `paper/dist/`:

| File | Use |
|---|---|
| `main.pdf` (also `paper/main.pdf`) | Named version, 17 pages |
| `contextpilot-arxiv.tar.gz` | arXiv source upload; compiles from a clean copy |
| `contextpilot-anon.pdf` | Double-blind version: no author, no repository link |

## Venues

| Venue | Deadline | Status |
|---|---|---|
| arXiv | any time | Ready. A first submission to `cs.*` may need an endorsement |
| ICLR 2027 workshops (San Francisco, Apr 29–30) | Feb 1, 2027 on the two CFPs seen so far (SEA's is tentative) | Primary target. ICLR notifies accepted workshops on Nov 29, 2026; pick the workshop then |
| SIGMETRICS 2027, winter cycle | abstract Jan 4, paper Jan 11, 2027 | Stretch. Needs ACM format and a second workload or model |
| MLSys 2027 | Oct 30, 2026 | Passed |
| ICML 2027 | not checked | Stretch |

Check each date on the venue's own page before relying on it.

## Before a workshop submission
- [ ] Choose the workshop once the ICLR list is out, and read its page limit and anonymity rule.
- [ ] Move the paper into that workshop's template. The body is about 14 pages in this layout; a 9-page limit means moving the pilot, the horizon rules and the prediction-gap table to an appendix.
- [ ] Double-blind: the anonymous PDF still names `contextpilot`, `EVAL_PLAN.md` and "one user's logs", and the repository is public under that name. Use an anonymized mirror if the workshop asks for one.

## arXiv metadata
- **Title:** When Should an Agent Compact? Cache-Aware Rent-or-Buy Timing for LLM Agent Context
- **Categories:** cs.AI (primary); cs.PF, cs.SE
- **Comments:** 17 pages, 3 figures. Code and data: https://github.com/anuhtole/contextpilot
- **Abstract** (under arXiv's 1,920-character limit):

> Long-running LLM agents periodically compact their context, replacing history with a summary. Production harnesses trigger compaction at a fixed token count or a fixed fraction of the context window. We cast compaction timing as a rent-or-buy problem under prompt-cache pricing: held history pays cache-read rent on every call, and each compaction pays once for a summary and a cache rewrite. In steady state this is the Economic Order Quantity, so the cost-optimal compaction point depends on growth, summary cost and prices but not on the window. With every cost term measured on headless Claude Code, the model reproduces real bills to within 0.8%. At Claude Code prices the optimum is about 109k tokens of history, which makes the 150k API default near-optimal, while near-window triggers on 1M-token windows cost about 28% more in trace-driven simulation. In 13 real sessions designed to cross the optimum, savings were single-digit and not significant, and our recorded prediction of -35% failed; we decompose the gap. Replaying 16 real sessions against Claude Code's 490k auto-compaction point, an online rule would have cost 12% less, at five times as many compactions. A pre-registered dose-response experiment (30 real sessions, 0-8 compactions each) finds no recall loss per extra compaction (slope -0.05 facts, 95% CI -0.39 to +0.32), though 2 of 24 compacted runs silently lost most probed facts. Steady-state savings are a ceiling, not an expectation; the case for adaptive triggers is robustness across price regimes.

## What reviewers will push on
1. One model family and one vendor's prices in every real run.
2. The in-the-wild replay uses one user's logs (16 main sessions).
3. One synthetic task family; bugs fixed is saturated at 20/20.
4. No real-session cost saving is statistically significant (n = 4 paired orderings).
5. The dose-response arms did not all run in the same week.
