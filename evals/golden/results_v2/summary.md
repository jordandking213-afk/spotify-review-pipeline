# Golden-50 evaluation

Predictions: `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2`. Human labels: Jordan (`evals/golden/golden_50_human_labels_v2.csv`). Code comparison only.

| Measure | Strict (human primary label) | Lenient (also accepts human-marked alternatives) |
|---|---|---|
| topic agreement | 80% | 84% |
| intent agreement | 92% | 92% |
| severity agreement | 76% | 78% |
| all_three agreement | 62% | 64% |

- Valid predictions: 50/50 (missing/quarantined count as wrong: 0).
- Ambiguous cases marked by the human labeler: 15.
- Severity mean absolute error: 0.32.
- Sentiment within ±0.5 (declared tolerance): 98%; sentiment MAE: 0.14.
- Evidence quote is an exact substring: 50/50; overlaps the human's quote: 49/50.
- needs_review as a prediction: {'true_positive': 6, 'false_positive': 5, 'false_negative': 7, 'true_negative': 32, 'precision': 0.5455, 'recall': 0.4615}.

## Per topic

| Topic | Human count | Predicted count | Strictly correct |
|---|---|---|---|
| access | 1 | 0 | 0 |
| usability | 8 | 8 | 5 |
| playback | 2 | 5 | 1 |
| downloads | 1 | 1 | 1 |
| catalog | 5 | 6 | 4 |
| billing | 3 | 2 | 2 |
| support | 1 | 0 | 0 |
| other | 29 | 28 | 27 |

## Topic confusion (human → predicted, mismatches only)

- access->playback: 1
- billing->usability: 1
- catalog->usability: 1
- other->catalog: 2
- playback->usability: 1
- support->playback: 1
- usability->other: 1
- usability->playback: 2

## Disagreements (strict)

| Review | Human (topic/intent/sev) | Predicted | Ambiguous | Text |
|---|---|---|---|---|
| `292ce26a` | catalog/complaint/2 | catalog/complaint/3 | false | Staff must be full of mentally ill kool-aid heads. Banning conservative music that speaks truth. Spotify is doing all they can to protect pe |
| `991b6b3a` | billing/complaint/2 | usability/complaint/3 | false | Ads were okay, but limited functionality..it's just too much |
| `1fc8b08f` | usability/praise/1 | other/praise/1 | false | Duo Premium .... No ads at all! |
| `947821dc` | usability/complaint/3 | playback/complaint/3 | false | Very good but wen I play my song it o ly plays a little bit then it stops I updated my phone and it worked but it happend again they need to |
| `723f07de` | support/praise/1 | playback/complaint/4 | true | Update: I reached out to Spotify Support and with some help from Sarah I was able to get the app working again. Old Post:Normally, the app w |
| `01d453b0` | usability/complaint/3 | usability/complaint/2 | false | I like it but god I hate it when the music Interrupts my ads |
| `ac6cd66d` | other/unclear/1 | catalog/praise/1 | false | Lhat ng song nasa spotify |
| `46842184` | catalog/complaint/2 | catalog/complaint/3 | false | asem, lirik nya kdang gaada kek mana?? |
| `372d4e67` | usability/complaint/2 | usability/request/2 | false | Please ye ads ko thoda kumm Karo harr ek song ke baad ad 🙏🙄 |
| `3ddb3f4e` | usability/cancellation/4 | usability/cancellation/3 | false | Deleting this App. The new update suck, we can't choose our fvrt songs after some clicks, we can't CHOOSE song after a song played, and we c |
| `16d640e9` | billing/complaint/2 | billing/complaint/3 | false | It's my best music app but now it's not...everything basic features is premium.... |
| `215463ae` | access/complaint/4 | playback/complaint/4 | true | What is happening with Spotify?? Recently I'm trying to play a song but it doesn't working. So I unstalled and thn again install it now I ca |
| `46c0b49f` | usability/complaint/2 | playback/complaint/5 | true | Are you out of your mind? This is dangerous! Listening to music in a normal volume and suddenly an add starts and my ears feel like they exp |
| `8c0546b0` | catalog/complaint/2 | catalog/complaint/3 | true | 1-Lyrics not getting loaded, 2-can't go back to or start song where to wanted. Pathetic update |
| `b58dd6f0` | catalog/request/1 | usability/request/1 | false | The only thing Spotify lacks is the ability to organize saved  albums/artists into collections. Would definitely deserve 5 stars if it  incl |
| `dceb14e7` | playback/complaint/2 | usability/complaint/3 | true | I gave one star because I can't give any less than that. the new update is sooooooo annoying like I can't even play the songs that I like an |
| `5fba12ea` | other/praise/1 | catalog/praise/1 | true | I find Spotify very good, it finds and play whatever music you want and also adds songs that you might like, judging from your playlist if y |
| `ac4e860a` | downloads/complaint/2 | downloads/complaint/3 | true | paying for subscribing but unable to play in offline mode really? |
| `d2f3874f` | billing/complaint/2 | billing/cancellation/3 | true | Too expensive and the free version is pretty much unusable with constant ads... Every two or three songs.. Forget it |

*Missing or quarantined predictions count as incorrect in agreement; MAE uses valid predictions only.*
*Fifty cases are a small diagnostic sample, not a precise population accuracy estimate.*
*The golden labels were completed after the enrichment prompt (enrich-v2) was frozen and did not influence any prompt, example, threshold or grouping rule.*

**Disclosure:** v2 revises 9 of Jordan's 50 labels **after seeing the model's predictions**, each to follow a cited
labeling rule (see `evals/golden/golden_v2_changelog.csv`). Revising after seeing predictions can favor the model,
so the original v1 labels and their results (`results_v1/`) are kept unchanged and both scores are reported.
No prompt, example, threshold or grouping rule was changed because of the golden set.
