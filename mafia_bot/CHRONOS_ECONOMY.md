# CHRONOS Economy v1.0

Status: **DRAFT — not active until the organizer approves the rules and migration 004 is applied.**

This model is a closed, non-monetary game economy. It is deliberately designed around cosmetics and progression rather than pay-to-win advantages. No CR, EX or XP may be bought for UAH, transferred to another player or cashed out.

## 1. Design principles

The model follows five standard game-economy principles:

1. Map every currency source (faucet) and sink. If sources permanently exceed sinks, balances accumulate and item prices stop mattering; if sinks exceed realistic income, players experience a grind wall. Unity's economy guides explicitly recommend mapping sources and sinks and balancing them against progression and player archetypes.
2. Model more than one engagement level. A player who attends occasionally must still earn something meaningful; active players should have aspirational items without gaining competitive advantages.
3. Separate competitive ranking from the cosmetic economy. iMafia ranking, the 30% game participation qualification and Top-10 placement are based on confirmed game results only. XP, CR, EX, Mini App usage and cosmetic purchases never increase sporting rank.
4. Keep all grants and spending in an append-only ledger with idempotency keys. Re-imports or retries must not create currency from the same game twice.
5. Start with a deterministic spreadsheet-style simulation, then recalibrate against actual season data. This is a first-pass model, not a claim that exact player behaviour can be known in advance.

References:
- Unity, “What is an in-game economy”: https://unity.com/how-to/what-game-economy-guide-part-1
- Unity, “Building an in-game economy”: https://unity.com/how-to/building-game-economy-guide-part-2
- Unity, “Designing a balanced in-game economy”: https://unity.com/how-to/design-balanced-in-game-economy-guide-part-3
- GDC, “Economic Balancing and Improved Monetization Through Clever Sink Design”: https://www.gdcvault.com/play/1021008/Economic-Balancing-and-Improved-Monetization

## 2. Season quantities and assumptions

The core CHRONOS season has:

| Quantity | Calculation | Result |
|---|---:|---:|
| Regular evenings | 9 | 9 |
| Regular games | 9 × 5 | 45 |
| Intermediate finals | 3 × 8 | 24 |
| Core games | 45 + 24 | 69 |
| Players per game | 10 | 10 |
| Aggregate core participations | 69 × 10 | 690 |
| Main Final games | 10 | 10 |
| Main Final participants | Top 10 | 10 |

**Important distinction:** 690 is the aggregate number of player-game participations used for season synchronization. It is not 690 games per player. A single player can play at most 69 core games if they appear in every game. A Main Final Top-10 player can play up to 10 additional games. Those Main Final games are recorded, but are excluded from the 690 core synchronization target.

For modeling:
- Minimum qualification at the end of a full core season: ceil(69 × 30%) = 21 distinct core games.
- A final invitation is an eligible attendance opportunity only for the player who received it.
- A Top-10 player who declines or does not attend a personal final invitation keeps that missed opportunity in the attendance denominator.
- A player who was never invited is not penalized for that final.
- An evening attendance reward is granted once per event, not once per game.

## 3. Currency architecture

| Currency | Purpose | Sources | Sinks |
|---|---|---|---|
| CR | Main cosmetic currency | Confirmed Mafia game participation; attended evening | CR cosmetics |
| EX | Prediction reward currency | Correct free predictions only | EX cosmetics |
| XP | Progression and level display | Confirmed games, attended evenings, capped mini-game completions | No spending; progression only |

No exchange rate exists between CR, EX, XP and UAH. There is no currency conversion, player-to-player market, paid booster, transfer or cashout. CR, EX and XP balances carry forward between seasons; earning caps and mini-game repeat limits are season-scoped, while the six-forecast EX Store unlock is a one-time lifetime milestone. To prevent multi-season stockpiling from exhausting the catalogue, new cosmetic sinks must be added in each future season.

## 4. Income formulas

### CR

CR = 5 × confirmed_games + 10 × attended_evenings

The 5 CR per game rewards the actual game participation. The separate 10 CR evening reward encourages showing up, but is issued only once even if the player played five or eight games that night.

A Top-10 player who plays all 69 core games across the 12 progression evenings earns:

69 × 5 + 12 × 10 = 465 CR

If that player also attends and plays all 10 Main Final games on the separate 13th evening:

79 × 5 + 13 × 10 = 525 CR

### XP

XP = 10 × confirmed_games + 5 × attended_evenings + minigame_XP

Mini-game XP:
- First completed CODE BREAKER: 20 XP.
- First completed MEMORY: 20 XP.
- Up to 10 repeat completed sessions across both game types: 5 XP each.
- Maximum mini-game XP per player per season: 20 + 20 + 10 × 5 = 90 XP.

XP does not buy items and cannot be converted into cash. The current level calculation is 100 XP per level; XP has no competitive ranking effect.

### EX from free predictions

A forecast costs zero EX. A correct forecast earns a reward based on the frozen probability of the selected player:

reward_EX = clamp(5, 100, round(5 / probability))

Examples:

| Estimated probability | Reward if correct | Expected reward before rounding |
|---:|---:|---:|
| 5% | 100 EX | 5 EX |
| 10% | 50 EX | 5 EX |
| 12.5% | 40 EX | 5 EX |
| 20% | 25 EX | 5 EX |
| 50% | 10 EX | 5 EX |
| 100% | 5 EX | 5 EX |

A wrong prediction earns zero and costs nothing. Any player may forecast even when registered for that evening, but cannot forecast themselves. A player may make one forecast in each market, up to three forecasts per event (TOP1, TOP2, TOP3). Candidate probabilities and rewards are frozen when the markets open. If the registered event roster changes, the market is voided; no currency is debited or refunded because no stake was taken.

Limits:
- At most 3 forecasts per event.
- 39 possible forecasts across 13 season events.
- Expected EX income at the 5 EX target value: 39 × 5 = 195 EX.
- Hard EX earning cap: 500 EX per player per season.
- EX Store opens permanently after six accepted non-void forecasts across the player's CHRONOS history (normally two events if all three markets are used).
- The 5 EX reward floor preserves the expected-value curve even for very high-probability candidates. The 100 EX ceiling reduces the expected value of very unlikely candidates below 5 EX, limiting the faucet on long shots.

The candidate probability model is a Plackett–Luce simulation based on a confirmed iMafia ranking snapshot. It is a forecast heuristic, not a promise of winning probability.

**Pilot model policy (three first evenings):**
- Keep the existing feature weights fixed during the first three CHRONOS evenings: base points/game 40%, net bonus points/game 20%, win rate 20%, and inverse current rank 20%. The single historical check below is not enough evidence to tune weights.
- Feature definitions match the implementation: base points/game = (total points − bonus points) / games played; net bonus points/game = bonus points / games played; win rate = wins / games played; rank signal = 1 / rank position. The 10-game prior shrinks each per-game rate toward the median of the registered roster, reducing noise from short histories. This avoids counting iMafia's included bonus component twice and avoids rewarding a player merely for having more games.
- If a registered player has no row in the latest snapshot, the market opener adds an empty cold-start row. The model replaces missing/zero-history features with the median of the known candidates in that roster. A newcomer is not assigned zero skill or automatically placed last.
- If no candidates in the roster have prior games, the feature values are equal and the model produces an approximately uniform forecast.
- Candidate probabilities and rewards remain frozen when markets open. Model changes apply only to future markets; never recalculate a forecast using post-event data.

After each of the first three evenings, record the frozen TOP1/TOP2/TOP3 probabilities and actual placements. Review:
1. Top-1/top-2/top-3 hit rates against a uniform 1/N baseline.
2. Multiclass log loss and Brier score for each placement market.
3. Calibration by probability bands (predicted probability versus actual frequency), with sample counts shown.
4. Share of participants receiving neutral cold-start treatment and the effect of missing ranking rows.
5. EX issued per accepted forecast and the distribution of predicted probabilities.

Do not reweight the model after the first evening. After three evenings, decide whether to retain it or version a change. Three evenings are still a small sample; treat the result as an initial operational review, not proof of statistical calibration.

### Preliminary historical smoke test — 25 October 2026

Mafia Scout lists the KMC evening on 25 October 2026 as 8 games and 10 players. The observed evening podium was Кубик, Бетховен and Bananchikk. For a retrospective check, the model inputs were reconstructed by subtracting each player's 25 October contribution from their cumulative KMC totals; the two players with no prior KMC games were given the new neutral cold-start treatment. The pre-evening rank positions were reconstructed approximately from the cumulative ranking, not taken from an archived pre-evening snapshot.

Using the existing 40/20/20/20 model, a fixed seed and 12,000 Plackett–Luce simulations, the realized placements had these probabilities:
- Кубик — 10.47% for TOP1 (actual 1st).
- Бетховен — 8.98% for TOP2 (actual 2nd).
- Bananchikk — 15.80% for TOP3 (actual 3rd).

The model's highest TOP1 estimate was for Sakura (about 22.55%), so it did not identify the actual winner as the favorite. Across these three realized outcomes, the summed log loss was about 6.51 versus 6.91 for a uniform 10-player baseline; mean multiclass Brier score was about 0.884 versus 0.900 for the uniform baseline. This is only one evening and the input snapshot is reconstructed, so these numbers are a smoke test, not a reliable estimate of long-run accuracy. The weights are therefore kept unchanged for the first three CHRONOS evenings.

## 5. Activity Score and the UAH 500 bonus

The Activity Score is a 0–100 cumulative coefficient:

Activity Score = 80 × attendance_ratio + 15 × app_ratio + 5 × minigame_ratio

Where:
- attendance_ratio = attended_eligible_slots / eligible_slots
- app_ratio = min(unique_event_actions, 13) / 13
- minigame_ratio = min(completed_minigames, 5) / 5
- Activity Coefficient = Activity Score / 100

The app component counts at most one positive verified interaction per distinct season event; opening an event detail is enough, while repeat views and repeat clicks in the same event do not add points. This cap is 13 because the season has at most 13 scheduled events. Mini-game completions are capped at five. Both are verified server-side and written with unique source keys. The Activity Score is not part of the sporting iMafia ranking.

The separate 500 UAH activity bonus is allocated proportionally among the **initial Top 10 invited to the Main Final who meet the 30% game qualification**. It does not reduce the fixed prizes.

For eligible players:

exact_share_i = 500 × Activity_Score_i / sum(Activity_Score of eligible players)

Amounts are floored to whole UAH, then the remaining UAH are allocated by largest fractional remainder. Ties are resolved by the locked Main Final rank. This guarantees that the total allocation is exactly 500 UAH.

Example with ten eligible Top-10 players scoring 100, 98, 96, 94, 92, 90, 88, 86, 84 and 82 points:

| Locked rank | Score | Bonus |
|---:|---:|---:|
| 1 | 100 | 55 UAH |
| 2 | 98 | 54 UAH |
| 3 | 96 | 53 UAH |
| 4 | 94 | 52 UAH |
| 5 | 92 | 51 UAH |
| 6 | 90 | 49 UAH |
| 7 | 88 | 48 UAH |
| 8 | 86 | 47 UAH |
| 9 | 84 | 46 UAH |
| 10 | 82 | 45 UAH |
| **Total** | **910** | **500 UAH** |

If fewer than ten initial Main Final invitees meet qualification, the 500 UAH pool is still split among those eligible players. The model does not pay the unused amount to ineligible players.

### Fixed prize fund

| Event | 1st | 2nd | 3rd | Total |
|---|---:|---:|---:|---:|
| Each intermediate final | 1,000 | 700 | 300 | 2,000 |
| Three intermediate finals | 3,000 | 2,100 | 900 | 6,000 |
| Main Final | 3,000 | 2,000 | 1,000 | 6,000 |
| Activity bonus pool | — | — | — | 500 |
| **Total season commitment** | | | | **12,500 UAH** |

The fixed place prizes are not multiplied by the Activity Coefficient. The coefficient applies only to the separate 500 UAH pool. This avoids turning a published 1,000/700/300 UAH prize into a smaller variable payout after the fact.

The bonus is calculated only after the season is completed and the Main Final bot event is closed. It is saved as a draft allocation and requires an admin approval step. The platform does not transfer money.

## 6. Cosmetic item pricing

### CR catalogue

| Item | Price | Share of minimum qualifier's 155 CR |
|---|---:|---:|
| Neon Frame | 80 CR | 52% |
| Cyan Aura | 120 CR | 77% |
| Signal Glasses | 100 CR | 65% |
| Chrono Chain | 140 CR | 90% |
| Operator Glove | 160 CR | 103% |
| Holo Frame | 180 CR | 116% |
| Pulse Aura | 220 CR | 142% |
| Chrome Visor | 260 CR | 168% |
| Timekeeper Frame | 320 CR | 206% |

A player who only just qualifies can buy at least one entry item. A regular player with 245 CR can afford two low/mid-range cosmetics; an active player has access to premium items. The top price is aspirational but remains reachable over a full season.

Total one-time CR catalogue sink capacity: **1,580 CR per player**. Inventory uses unique item ownership, so no duplicate purchase loop is created.

A 0/1 knapsack check (each item can be bought once) gives these maximum purchase baskets:
- Minimum qualifier (155 CR): 1 item, maximum spend 140 CR, 15 CR left.
- Regular player (245 CR): 2 items, maximum spend 240 CR, 5 CR left.
- Active Top-10 after Main Final (525 CR): 4 items, maximum spend 520 CR, 5 CR left.

### EX catalogue

| Item | Price |
|---|---:|
| Golden Chip | 25 EX |
| Lucky Dice | 40 EX |
| High Roller | 55 EX |
| Money Vision | 80 EX |
| All In | 90 EX |
| Big Stake | 120 EX |
| Cash Blaster | 160 EX |
| House Owner | 180 EX |
| Jackpot Aura | 220 EX |
| Money Rain | 250 EX |
| The Whale | 250 EX |

Total one-time EX catalogue sink capacity: **1,470 EX per player**. The expected full-season EX income of 195 EX supports several entry/mid-tier items, while the 500 EX cap and higher prices leave premium goals for unusually successful forecasters. EX is a cosmetic reward; it does not affect mafia results or cash prizes.

The same unique-item basket check gives:
- Minimum qualifier (30 expected EX): 1 item, 25 EX spent, 5 EX left.
- Regular player (90 expected EX): 2 items, 80 EX spent, 10 EX left.
- Active Top-10 before Main Final (180 expected EX): 3 items, 175 EX spent; after Main Final (195 expected EX): 3 items, 195 EX spent.

All items remain disabled until catalogue prices and visual assets are approved by the organizer.

## 7. Simulation and balance check

The deterministic simulator includes different engagement archetypes:

| Archetype | Games | Attended evenings / eligible | App actions | Mini-games | Forecasts | CR | Expected EX | XP | Activity Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Minimum qualifier | 21 | 5 / 9 | 6 | 3 | 6 | 155 | 30 | 280 | 54.37 |
| Regular player | 35 | 7 / 9 | 10 | 5 | 18 | 245 | 90 | 440 | 78.76 |
| Active Top-10 before Main Final | 69 | 12 / 12 | 12 | 5 | 36 | 465 | 180 | 805 | 98.85 |
| Top-10 misses one intermediate final but attends Main Final | 71 | 12 / 13 | 13 | 5 | 36 | 475 | 180 | 825 | 93.85 |
| Active Top-10 including Main Final | 79 | 13 / 13 | 13 | 5 | 39 | 525 | 195 | 910 | 100.00 |

XP values include the capped mini-game XP above. If the active Top-10 player completes all 12 eligible mini-game sessions instead of five, they gain up to 90 mini-game XP and reach 945 XP including the Main Final games.

### Does the economy reconcile?

- **No free conversion loop:** CR, EX and XP cannot be exchanged with each other or UAH.
- **Faucets are capped/observable:** game and attendance grants use idempotency keys; mini-game repeats are capped; EX has a 500-per-season cap. Wallet balances carry forward; future seasons must add new cosmetic sinks to absorb accumulated balances.
- **Sinks are real:** cosmetic purchases debit the same ledger that receives grants, and inventory prevents duplicate purchases.
- **Minimum progress is meaningful:** the minimum qualifier has 155 CR and can afford an 80 CR entry item. Six forecasts have an expected value of about 30 EX, enough for the 25 EX entry item.
- **Active progress is aspirational:** a full core Top-10 player earns 465 CR and can buy a 320 CR premium item; playing all Main Final games raises the ceiling to 525 CR.
- **Prize budget balances:** 6,000 UAH intermediate finals + 6,000 UAH Main Final + 500 UAH activity bonus = exactly 12,500 UAH.
- **Bonus allocations reconcile:** largest-remainder rounding guarantees the exact pool total, with no fractional kopecks or extra UAH created.
- **Competitive fairness is preserved:** currency, mini-games and cosmetics do not affect iMafia ranking or fixed place prizes.

This is a pre-season model. It proves that the formulas and planned budgets reconcile; it does not prove actual demand, player attendance or average forecast accuracy. After the first 2–3 evenings, review: median CR/EX balances, percent of players who can afford each price tier, purchased item distribution, forecast reward/forecast ratio, source-to-sink ratio, and bonus-score spread. Change prices or rates only with a versioned economy update, not by silently changing a live season.

## 8. Approval and rollout

Economy v1.0 is stored as DRAFT. The admin interface requires the Activity Score to be approved before economy approval, and requires both before prediction approval. Mini-game XP and game-based CR/XP are gated on economy approval. Store catalogue entries remain disabled until separately enabled.

Apply migration 004 only after reviewing migrations 001–003 and validating the schema in a staging Neon branch. No migration, approval, deployment or season activation is performed merely by adding this model.


## 9. Live monitoring and guardrails

The Admin Console's Economy report reads the actual ledger and catalogue, not the forecast table. It shows per-currency:
- Issued = sum of positive ledger entries.
- Removed = absolute sum of negative ledger entries.
- Net Change = Issued − Removed.
- Holders, average / median positive balance and maximum balance.
- Sink/Faucet Ratio = Removed / Issued.
- Active catalogue items, total enabled basket value and completed purchases.
- Planned / drafted / approved / paid UAH prizes and Activity Bonus.

The app logs the first verified event-detail view per player and event. Reopening the same detail does not farm extra Activity Score. Registration and accepted forecasts are also event-level interactions; the bonus calculator counts distinct event IDs, not raw button clicks.

Guardrails:
- Season activation is blocked until Activity Score and core Economy are approved. Prediction Exchange may remain DRAFT while its probability model is back-tested.
- Catalogue prices are editable only while the season is DRAFT and before Economy approval. Once the season is active or the rule set approved, an item may be enabled/disabled but its price cannot be changed mid-season.
- Reconciliation is a manual admin operation after confirmed imports. It is idempotent and does not alter historical game scores.
- The virtual ledger never pays UAH. Fixed awards and the Activity Bonus are separate, manually approved cash obligations.

Do not treat Sink/Faucet Ratio as a weekly target. Players may legitimately save for premium items. Use it together with the median balance and purchase conversion: a low ratio alone is not a failure if the season is young or players are saving; a persistently low ratio alongside growing median balances and no purchases indicates that new cosmetic sinks are needed.

