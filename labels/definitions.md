# Label definitions — FINAL (labels-v2), approved by Jordan, used for the full run

**Status:** final. This version is `labels-v2`, part of every record's `label_config`
(`gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2`). It includes Jordan's decisions from 2026-10-03 (both rounds;
see section 7) and was approved as final by Jordan on 2026-10-10. `labels-v1` was an earlier draft used only for the
5-review connection test.

## How to read this file

| Marker | Meaning |
|---|---|
| **[OFFICIAL]** | Copied from `GRADING_CONTRACT.md` (course-supplied). Not editable; we must use these exactly. |
| **[SUGGESTED]** | Proposed by Claude and approved by Jordan as part of this final version. |
| **[DECIDED]** | Jordan made the decision; his reasoning is recorded in section 7. |

All examples come from `analysis_10000.csv` (development set). **None come from the golden 50**, and the
golden 50 must never be added here.

---

## 1. Topic — exactly one per review [OFFICIAL]

| `topic` | Definition |
|---|---|
| `access` | Login, signup, password or account access |
| `usability` | Navigation, controls, layout, queue/playlist management, ad interruptions |
| `playback` | Playback failure, crashes, lag, connection failures, audio quality, resource use |
| `downloads` | Downloading, saved music, offline listening, disappearing downloads |
| `catalog` | Missing songs/artists, search/discovery, recommendations, lyrics availability |
| `billing` | Price, charges, subscriptions, paywalls, premium entitlement; explicitly premium-only controls go here |
| `support` | Contacting support and the support response |
| `other` | General praise/criticism, unrelated content, or no supported specific topic |

**Topic rules [OFFICIAL]**
- Choose the problem with the highest supported severity. On a tie, choose the first specific problem mentioned.
- For a positive review, choose the first specific praised feature; general praise is `other`.
- Mentioning a paid plan alone does not make the topic `billing`. A subscription failing to activate does;
  music crashing for a paying customer is `playback`.
- Classify the review text itself. Stars and other metadata must not substitute for reading the text.

**Topic rule [DECIDED, decision 5b]:** "easy to use" / "easy to navigate" → `usability`; bare "simple" or "easy" with no
feature named → general praise (`other`, or the first specific feature mentioned after it).

## 2. Intent — exactly one, in this precedence order [OFFICIAL]

1. `cancellation` — explicitly leaving, uninstalling, cancelling, or threatening to do so
2. `complaint` — negative experience, including mixed praise/criticism
3. `request` — desired change without a reported failure
4. `praise`
5. `unclear`

- Bare boycott slogans and unrelated/meaningless text are `unclear`, unless there is a product complaint or
  explicit personal departure.
- General "bad app" is a complaint; do not infer a specific defect.

## 3. Severity — integer 1–5 [OFFICIAL]

| `severity` | Shared meaning |
|---|---|
| 1 | No reported problem: praise, neutral/unclear content, or a pure feature request |
| 2 | Dislike, generic criticism, minor annoyance, or a cosmetic issue; no supported functional loss |
| 3 | A degraded or restricted function; some use or workaround remains |
| 4 | A clearly blocked core task, such as inability to log in or play music |
| 5 | Explicit serious financial, privacy, or data harm; an expensive plan, a crash, or angry language alone is insufficient |

- Cancellation intent does not automatically raise severity.
- Missing context should trigger `needs_review`; do not invent impact.
- Stars, angry language, or cancellation intent alone do not establish severity.

**Severity rules [DECIDED]**
- **Paywalls (decision 1b):** severity 3 when a specific feature is named as locked behind Premium; a vague
  "forcing me to buy premium" with no feature named is severity 2.
- **Support (decision 2):** 2 if only annoyed, 3 if a problem stays unresolved, 4 if blocked.
- **Unwanted feature with no off switch (decision 3):** 2.
- **Data or money loss (decision 4):** 5 only when serious data, money, or privacy harm is stated.

## 4. Other required fields

| Field | Rule |
|---|---|
| `sentiment` | **[DECIDED]** A number from −1 to 1 using five anchors: −1 very negative · −0.5 negative · 0 neutral or evenly mixed · 0.5 positive · 1 very positive. For evaluation, a prediction within **±0.5** of the human value counts as agreement; mean absolute error is also reported. *(The tolerance must be declared before evaluation.)* |
| `evidence_quote` | **[OFFICIAL]** An exact substring of the original review text. Code checks it character for character. **[SUGGESTED]** For short reviews, use the whole text; for longer ones, use the clause that supports the topic. |
| `entities` | **[DECIDED]** A list of product-feature terms that appear in the text (e.g. `ads`, `lyrics`, `shuffle`, `offline`, `login`, `premium`, `podcast`, `queue`). Code matches these against a fixed vocabulary, so nothing is invented. An empty list is allowed. |
| `paywall_named_feature` | **[DECIDED, decision 1c]** `true` when the review complains that a *specific named* feature or control is locked behind Premium (e.g. lyrics, skipping, queue). `false` otherwise, including vague "forcing premium" complaints and paying users whose Premium isn't recognized. Not a graded field. It exists so the memo can show the ranking if paywall complaints were severity 2 instead of 3. |
| `needs_review` | **[SUGGESTED]** `true` when the label depends on information the text doesn't give, such as a speculated cause, an unclear language, sarcasm, or two problems with the same severity in a different order. This is a prediction we evaluate, not a guarantee. |

## 5. Optional subtopics — DROPPED (decision 7)

No subtopics are used. Each review gets one of the 8 official topics only.

---

## 6. Worked examples

Each example applies the shared rules to a real development review. Labels were proposed by Claude, with every
judgment call decided by Jordan (section 7), and approved by Jordan in this final version. "Rule applied" points to the
official rule or decision used.
E3 was dropped (decision 9: it overlapped E2). E26–E29 were added by Jordan (decision 1d); their topic, intent and
severity are Jordan's, and only their sentiment values are Claude's suggestion.
`paywall_named_feature` is `true` for E8, E9 and E26, and `false` for every other example.

| # | Review ID (short) | Review text (exact) | Topic / intent / severity / sentiment | Rule applied |
|---|---|---|---|---|
| E1 | `12efd15d` | "I can't login to the app, it keep saying that there's no internet connection, whereas everything else on my phone is connected to the internet." | access / complaint / 4 / −0.5 | Severity 4: "inability to log in" |
| E2 | `5e42046c` | "Listen to my music almost everyday,this app is great. But the bad thing is that it gives too many ads, i would have hiven it 5 stars. Apart from that this app is great" | usability / complaint / 2 / 0.5 | Mixed praise/criticism → complaint; ad interruptions → usability; annoyance → 2 |
| E4 | `55cc3abf` | "The latest update has caused my app to crash I cant open the app please fix." | playback / complaint / 4 / −0.5 | Crashes → playback; can't open = blocked core task |
| E5 | `b895eb46` | "It good but it crash to at times" | playback / complaint / 3 / 0 | Occasional crash, use remains → 3 |
| E6 | `3899ed22` | "Paying for premium and certain podcasts are suddenly lagging. Unacceptable" | playback / complaint / 3 / −0.5 | "Mentioning a paid plan alone does not make the topic billing" |
| E7 | `9f7a013a` | "Nice app but why can't the lyrics of song on my playlist load?" | catalog / complaint / 3 / 0 | Lyrics availability → catalog |
| E8 | `d635d6c8` | "Why are lyrics premium!? There is literally no need to keep lyrics premium I'm sorry Spotify 1 star from me. Very disappointed:(." | billing / complaint / **3** / −1 | Paywall → billing; a named feature (lyrics) locked behind Premium → 3 (decision 1b) |
| E9 | `a3605554` | "Recent update really sucks. The ability to skip a song or go to previous song has been removed from non subscribed users." | billing / complaint / **3** / −1 | "Explicitly premium-only controls go here" → billing, not usability; named controls (skip, previous) locked → 3 (decision 1b) |
| E10 | `16929558` | "I paid my subscription and im still getting a pause subscription screen and can't access my music...... help me" | billing / complaint / 4 / −0.5 | "A subscription failing to activate" → billing; can't play = blocked |
| E11 | `d7f0416d` | "Your customer service members seriously need retraining on customer service. Half an hour being ignored, each message being read and ignored. No wonder why people are turning on Spotify! Absolute waste of space of an app" | support / complaint / **2** / −1 | Support response → support. Under decision 2, the review shows only annoyance at being ignored; no unresolved problem or blocked task is stated → 2 |
| E12 | `2c2fefc7` | "Always great! Even the support team is amazing!" | support / praise / 1 / 1 | First *specific* praised feature; "Always great" is general |
| E13 | `3b002c9f` | "The app automatically starts every time I connect to my car. The developer offers no way to turn this feature off, so I'm uninstalling this app and switching to a different service." | usability / cancellation / **2** / −0.5 | Cancellation takes precedence; controls → usability; annoyance, music still plays → 2 (decision 3); cancellation doesn't raise severity |
| E14 | `6531323c` | "All good, but I wish we could choose the preferred languages we want to listen to." | catalog / request / 1 / 0.5 | Desired change, no failure → request, severity 1; discovery → catalog (decision 5) |
| E15 | `0b5db00e` | "DEAR DEVELOPER, WE NEED A CHAT FEATURE ON SPOTIFYY" | other / request / 1 / 0 | No supported specific topic → other |
| E16 | `1452ccc8` | "This app Sweden I boycott Here the holy book was burnt Boycott Sweden" | other / unclear / 1 / −0.5 | "Bare boycott slogans … are unclear" |
| E17 | `7fd63051` | "I uninstalled this app as a form of protest and boycott due to the fact that the Swedish Government allows the burning of the HOLY QUR'AN." | other / cancellation / 1 / −0.5 | Explicit personal departure → cancellation; no product problem → 1 |
| E18 | `f5cc511f` | "Worst app ever they only care about money" | other / complaint / 2 / −1 | "General 'bad app' is a complaint; do not infer a specific defect." "Money" names no price or charge, so not billing (decision E18) |
| E19 | `305c3fe1` | "Why am I paying for this? Unable to login, can not reach tech support. Looks like the account was hacked." | access / complaint / 4 / −1, `needs_review: true` | "Looks like … hacked" is speculation, not explicit harm, so the highest *supported* severity is the blocked login (4) |
| E20 | `d87536c5` | "Top algorithm, but again hacked ,can't even recover the playlists set by me last week ,cost over three hundred dollars,per week for nothing ," | access / complaint / **5** / −0.5, `needs_review: true` | Stated hack plus lost playlists = serious data harm → 5 (decision 4). `needs_review` stays true because the dollar figure is unclear |
| E21 | `45c561b9` | "The update made the app useless .... Uninstall krdia ye app ab bekar hai ... Wynk hi theek h" | other / cancellation / 2 / −1 | Hindi-English mix. Claude's rough reading: "uninstalled it, this app is useless now … Wynk is fine." Explicit departure; generic criticism → 2 |
| E22 | `cf71ae94` | "Simple easy and literally every song at your finger tips, love it for out of signal areas as you have your play list offline. Lots of ebooks aswell as podcasts." | **catalog** / praise / 1 / 1 | First specific praised feature; "Simple easy" is general praise (decision E22) |
| E23 | `4aee0d75` | "Good" | other / praise / 1 / 0.5 | General praise → other |
| E24 | `4fa17991` | "Everytime my phone resets, Spotify ignores the SD card and my downloads disappear and I have to download everything again. It's very annoying." | downloads / complaint / 3 / −0.5 | "Disappearing downloads" → downloads; workaround (re-download) remains → 3 |
| E25 | `bcb0dce9` | "Good app there wasn't one song I could not find download it u won't regret it I promise" | catalog / praise / 1 / 1 | Trap: "download it" means *install the app*, not the downloads feature. First specific praise is song availability → catalog |
| E26 | `f66a61ed` | "Playing music from playlist in a queue is now a premium feature. What a joke." | billing / complaint / 3 (Jordan) / −0.5 (suggested) | Named feature (queue) locked behind Premium → 3 (decision 1b). Paired with E27 |
| E27 | `86adc9b6` | "Very bad experience ever faced by any app. They are literally forcing us to purchase Spotify premium." | billing / complaint / 2 (Jordan) / −1 (suggested) | Vague "forcing premium", no feature named → 2 (decision 1b). Paired with E26 |
| E28 | `f6f9c680` | "@spotifyindia worst one ever my premium account got logged out automatically which was linked with my phone number now when I try to log in using my phone number it shows check your number and try again even though my number is co[…]" | access / complaint / 4 (Jordan) / −1 (suggested) | A Premium mention doesn't make it billing; can't log in = blocked → 4 |
| E29 | `b06534cf` | "It keeps saying that I'm trying to use premium features, and that I should upgrade, meanwhile the exact same app clearly says I have a premium account when you click on m[…]" | billing / complaint / 3 (Jordan) / −0.5 (suggested) | Premium entitlement not recognized → billing; restricted function → 3. Not a paywall complaint, so `paywall_named_feature` = false |

---

## 7. Decision log (Jordan, 2026-10-03, two rounds)

The "Jordan's reasoning" column is Jordan's own wording: in "quotes", or in *italics* where his text itself
contains quotation marks. Where Claude pointed out an inaccuracy against the official rules, Jordan chose the
correction; the note column says so.

| # | Decision | Jordan's reasoning | Note |
|---|---|---|---|
| 1 | Paywalled features (E8, E9) → severity **3** | "for more accuracy in the paywall issue's score" | Word for word |
| 2 | Support problems → **conditional rule** | "2 if only annoyed, 3 if a problem stays unresolved, 4 if blocked" | Jordan adopted option (b) after Claude noted that a fixed 3 conflicted with his test. Under this rule E11 = 2. |
| 3 | Unwanted feature with no off switch (E13) → severity **2** | "2 as it reflects being annoying" | Jordan removed a clause that based severity on the desired ranking, and a stray "a" |
| 4 | Stated hack plus data loss (E20) → severity **5** | "5 for when serious data, money, or privacy harm is stated" | Jordan added "serious" and "privacy" to match the official level-5 rule |
| 5 | E14 topic → **catalog** | "Catalog as the language of the songs sound like content discovery" | Word for word |
| 6 | Sentiment agreement → **±0.5**, plus mean absolute error | "+/- 0.5 and report the mean absolute error to avoid the claim that tolerance hides errors" | Word for word |
| 7 | Subtopics → **dropped** | "Drop even though the specificity would be lacking but dropping subtopics reduces how many output tokens each review needs" | Jordan corrected "cost per token" (the price per token doesn't change) |
| 8 | Entities → **code-matched vocabulary** | "Match the feature words with code to keep cost down and avoid hallucinations even if synonyms are not caught" | Word for word |
| E18 | "Worst app ever they only care about money" → **other / complaint / 2**, not billing | — | Jordan agreed with Claude's suggested label; no reasoning text recorded |
| E22 | E22 topic → **catalog** | "simple easy does not say what is easy, I considered it as praise in general and took the first specific feature, which is every song being available, which is catalog" | Word for word |
| 1b | Paywall severity **refined**: 3 only when a specific feature is named | *severity 3 when a specific feature is named as locked behind Premium. Vague "forcing me to buy premium" with no feature named = severity 2.* | Round 2; word for word from Jordan's note. Also settles the connection-test case "this app only made for premium users" (no feature named → 2) |
| 1c | Memo **sensitivity check**: the ranking if paywall complaints were severity 2 | "Please add a sensitivity check in the memo showing the ranking if these were 2." | Round 2. Implemented with a `paywall_named_feature` true/false model output instead of subtopics (Jordan: "add small paywall_named_feature true/false output instead") |
| 1d | Add examples E26–E29 | — | Round 2; labels are Jordan's, from his note |
| 2 | Support rule **reaffirmed**, E11 = 2 | "Keep the recorded rule E11 = 2" | Round 2. Jordan's note had proposed E11 = 3; Claude pointed out it conflicted with the note's own test, and Jordan kept the recorded rule |
| 5b | "easy to use" / "easy to navigate" → usability; bare "simple/easy" → general praise | *"easy to use" / "easy to navigate" → usability; bare "simple/easy" → general praise.* | Round 2; word for word |
| 7 | Subtopics **stay dropped** | — | Round 2. Jordan's note said "keep the list"; after Claude flagged the conflict, Jordan chose the `paywall_named_feature` output instead |
| 9 | Drop E3 (overlaps E2); Jordan writes the reasoning column himself | *drop E3 (overlaps E2). I'll write my own reasoning for the rest — please don't fill in the "Your reasoning" column for me.* | Round 2; word for word |
| Final | File approved as **final** (`labels-v2`); the empty "Your reasoning" column removed, since each example already cites the rule it applies and judgment calls are explained in this log | — | 2026-10-10, Jordan |
