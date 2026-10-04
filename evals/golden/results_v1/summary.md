# Golden-50 evaluation

Predictions: `gpt-6-luna|effort=none|enrich-v2|schema-v2|labels-v2`. Human labels: Jordan (`evals/golden/golden_50_human_labels_v1.csv`). Code comparison only.

| Measure | Strict (human primary label) | Lenient (also accepts human-marked alternatives) |
|---|---|---|
| topic agreement | 76% | 80% |
| intent agreement | 92% | 92% |
| severity agreement | 68% | 70% |
| all_three agreement | 54% | 56% |

- Valid predictions: 50/50 (missing/quarantined count as wrong: 0).
- Ambiguous cases marked by the human labeler: 15.
- Severity mean absolute error: 0.44.
- Sentiment within ±0.5 (declared tolerance): 98%; sentiment MAE: 0.14.
- Evidence quote is an exact substring: 50/50; overlaps the human's quote: 49/50.
- needs_review as a prediction: {'true_positive': 6, 'false_positive': 5, 'false_negative': 7, 'true_negative': 32, 'precision': 0.5455, 'recall': 0.4615}.

## Per topic

| Topic | Human count | Predicted count | Strictly correct |
|---|---|---|---|
| access | 2 | 0 | 0 |
| usability | 8 | 8 | 4 |
| playback | 2 | 5 | 1 |
| downloads | 1 | 1 | 1 |
| catalog | 5 | 6 | 4 |
| billing | 1 | 2 | 1 |
| support | 1 | 0 | 0 |
| other | 30 | 28 | 27 |

## Topic confusion (human → predicted, mismatches only)

- access->playback: 1
- access->usability: 1
- catalog->usability: 1
- other->catalog: 2
- other->usability: 1
- playback->usability: 1
- support->playback: 1
- usability->billing: 1
- usability->other: 1
- usability->playback: 2

## Disagreements (strict)

| Review | Human (topic/intent/sev) | Predicted | Ambiguous | Text |
|---|---|---|---|---|
| `292ce26a` | catalog/complaint/2 | catalog/complaint/3 | false | Staff must be full of mentally ill kool-aid heads. Banning conservative music that speaks truth. Spotify is doing all they can to protect pe |
| `991b6b3a` | access/complaint/3 | usability/complaint/3 | false | Ads were okay, but limited functionality..it's just too much |
| `1fc8b08f` | usability/praise/1 | other/praise/1 | false | Duo Premium .... No ads at all! |
| `947821dc` | usability/complaint/3 | playback/complaint/3 | false | Very good but wen I play my song it o ly plays a little bit then it stops I updated my phone and it worked but it happend again they need to |
| `723f07de` | support/complaint/1 | playback/complaint/4 | true | Update: I reached out to Spotify Support and with some help from Sarah I was able to get the app working again. Old Post:Normally, the app w |
| `01d453b0` | usability/complaint/3 | usability/complaint/2 | false | I like it but god I hate it when the music Interrupts my ads |
| `ac6cd66d` | other/unclear/1 | catalog/praise/1 | false | Lhat ng song nasa spotify |
| `46842184` | catalog/complaint/2 | catalog/complaint/3 | false | asem, lirik nya kdang gaada kek mana?? |
| `5de7f95b` | other/unclear/2 | other/unclear/1 | true | We are boycotting Swedish app in our protest against Sweden for their desrecpect & desceration of our holy book Qur'an |
| `372d4e67` | other/complaint/3 | usability/request/2 | false | Please ye ads ko thoda kumm Karo harr ek song ke baad ad 🙏🙄 |
| `47f1406d` | playback/complaint/2 | playback/complaint/4 | false | Very poor updates as we cannot playback the songs and most bad updates are happening it is affecting the spotify quality |
| `3ddb3f4e` | usability/cancellation/4 | usability/cancellation/3 | false | Deleting this App. The new update suck, we can't choose our fvrt songs after some clicks, we can't CHOOSE song after a song played, and we c |
| `16d640e9` | usability/complaint/3 | billing/complaint/3 | false | It's my best music app but now it's not...everything basic features is premium.... |
| `215463ae` | access/complaint/4 | playback/complaint/4 | true | What is happening with Spotify?? Recently I'm trying to play a song but it doesn't working. So I unstalled and thn again install it now I ca |
| `46c0b49f` | usability/complaint/2 | playback/complaint/5 | true | Are you out of your mind? This is dangerous! Listening to music in a normal volume and suddenly an add starts and my ears feel like they exp |
| `283b5843` | other/unclear/2 | other/unclear/1 | true | Beth, we all got to give me a free dollar to go with 3 months, bro I can't be like |
| `2aa566c6` | usability/complaint/2 | usability/praise/1 | false | Nice app, very less advertising |
| `8c0546b0` | catalog/complaint/2 | catalog/complaint/3 | true | 1-Lyrics not getting loaded, 2-can't go back to or start song where to wanted. Pathetic update |
| `b58dd6f0` | catalog/request/3 | usability/request/1 | false | The only thing Spotify lacks is the ability to organize saved  albums/artists into collections. Would definitely deserve 5 stars if it  incl |
| `dceb14e7` | playback/complaint/2 | usability/complaint/3 | true | I gave one star because I can't give any less than that. the new update is sooooooo annoying like I can't even play the songs that I like an |
| `5fba12ea` | other/praise/1 | catalog/praise/1 | true | I find Spotify very good, it finds and play whatever music you want and also adds songs that you might like, judging from your playlist if y |
| `ac4e860a` | downloads/complaint/2 | downloads/complaint/3 | true | paying for subscribing but unable to play in offline mode really? |
| `d2f3874f` | billing/complaint/2 | billing/cancellation/3 | true | Too expensive and the free version is pretty much unusable with constant ads... Every two or three songs.. Forget it |

*Missing or quarantined predictions count as incorrect in agreement; MAE uses valid predictions only.*
*Fifty cases are a small diagnostic sample, not a precise population accuracy estimate.*
*The golden labels were completed after the enrichment prompt (enrich-v2) was frozen and did not influence any prompt, example, threshold or grouping rule.*
