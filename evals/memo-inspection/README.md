# Human inspection of the memo (full run)

`memo-v3-rejected.md` passed every automated check (each number came from a code-computed claim, every cited review
was in the evidence pack) but Jordan's inspection found its central comparison was false: it said playback had the
highest area severity sum (160,236, X8) "ahead of usability at 179,800 (X5)". The checks verify where numbers come
from, not whether comparisons between them are correct. The memo was regenerated as memo-v4, which receives the
area and issue orderings as code-computed facts, and the recommendation is decided at the issue level (Jordan's
decision, docs/decisions.md).

memo-v4 (`runs/full/memo/memo.md`, copied to `memo-v4-final.md`) passed all checks including the two new ones. Known
issues left as generated: a formatting typo in its sensitivity section, and one cited review (`98fee45a`) whose
paywall label relies on outside knowledge (see the main README, Limitations).
