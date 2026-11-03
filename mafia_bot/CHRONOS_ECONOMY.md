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

No exchange rate exists between CR, EX, XP and UAH. There is no currency conversion, player-to-player market, paid booster, transfer or cashout.

## 4. Income formulas

### CR

CR = 5 × confirmed_games + 10 × attended_evenings

The 5 CR per game rewards the actual game participation. The separate 10 CR evening reward encourages showing up, but is issued only once even if the player played five or eight games that night.

A Top-10 player who plays all 69 core games and attends all 13 possible evenings earns:

69 × 5 + 13 × 10 = 475 CR

If that player also plays all 10 Main Final games:

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

A wrong prediction earns zero and costs nothing. A player cannot forecast themselves. A player may make one forecast in each market, up to three forecasts per event (TOP1, TOP2, TOP3). Candidate probabilities and rewards are frozen when the markets open. If the registered event roster changes, the market is voided; no currency is debited or refunded because no stake was taken.

Limits:
- At most 3 forecasts per event.
- 39 possible forecasts across 13 season events.
- Expected EX income at the 5 EX target value: 39 × 5 = 195 EX.
- Hard EX earning cap: 500 EX per player per season.
- EX Store opens after six accepted non-void forecasts (normally two events if all three markets are used).
- The 5 EX reward floor preserves the expected-value curve even for very high-probability candidates. The 100 EX ceiling reduces the expected value of very unlikely candidates below 5 EX, limiting the faucet on long shots.

The candidate probability model is a Plackett–Luce simulation based on confirmed iMafia snapshot statistics. It is a forecast heuristic, not a promise of winning probability. It must be checked against actual outcomes after the season before the model is treated as calibrated.

## 5. Activity Score and the UAH 500 bonus

The Activity Score is a 0–100 cumulative coefficient:

Activity Score = 80 × attendance_ratio + 15 × app_ratio + 5 × minigame_ratio

Where:
- attendance_ratio = attended_eligible_slots / eligible_slots
- app_ratio = min(unique_event_actions, 13) / 13
- minigame_ratio = min(completed_minigames, 5) / 5
- Activity Coefficient = Activity Score / 100

The app component counts at most one positive verified interaction per distinct season event; repeat actions in the same event do not add points. This cap is 13 because the season has at most 13 scheduled events. Mini-game completions are capped at five. Both are verified server-side and written with unique source keys. The Activity Score is not part of the sporting iMafia ranking.

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

A player who only just qualifies can buy at least one entry item. A regular player with 270 CR can afford one mid-range cosmetic or a small combination; an active player has access to premium items. The top price is aspirational but remains reachable over a full season.

Total one-time CR catalogue sink capacity: **1,580 CR per player**. Inventory uses unique item ownership, so no duplicate purchase loop is created.

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

All items remain disabled until catalogue prices and visual assets are approved by the organizer.

## 7. Simulation and balance check

The deterministic simulator includes different engagement archetypes:

| Archetype | Games | Attended evenings / eligible | App actions | Mini-games | Forecasts | CR | Expected EX | XP | Activity Score |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Minimum qualifier | 21 | 5 / 9 | 6 | 3 | 6 | 155 | 30 | 280 | 54.37 |
| Regular player | 40 | 7 / 9 | 10 | 5 | 18 | 270 | 90 | 490 | 78.76 |
| Active Top-10 (core) | 69 | 13 / 13 | 15 | 5 | 39 | 475 | 195 | 810 | 100.00 |
| Top-10 misses one intermediate final but attends Main Final | 71 | 12 / 13 | 15 | 5 | 36 | 475 | 180 | 825 | 93.85 |
| Active Top-10 including Main Final | 79 | 13 / 13 | 15 | 5 | 39 | 525 | 195 | 910 | 100.00 |

XP values include the capped mini-game XP above. If the active Top-10 player completes all 12 eligible mini-game sessions instead of five, they gain up to 90 mini-game XP and reach 945 XP including the Main Final games.

### Does the economy reconcile?

- **No free conversion loop:** CR, EX and XP cannot be exchanged with each other or UAH.
- **Faucets are capped/observable:** game and attendance grants use idempotency keys; mini-game repeats are capped; EX has a season cap.
- **Sinks are real:** cosmetic purchases debit the same ledger that receives grants, and inventory prevents duplicate purchases.
- **Minimum progress is meaningful:** the minimum qualifier has 155 CR and can afford an 80 CR entry item. Six forecasts have an expected value of about 30 EX, enough for the 25 EX entry item.
- **Active progress is aspirational:** a full core Top-10 player earns 475 CR and can buy a 320 CR premium item; playing all Main Final games raises the ceiling to 525 CR.
- **Prize budget balances:** 6,000 UAH intermediate finals + 6,000 UAH Main Final + 500 UAH activity bonus = exactly 12,500 UAH.
- **Bonus allocations reconcile:** largest-remainder rounding guarantees the exact pool total, with no fractional kopecks or extra UAH created.
- **Competitive fairness is preserved:** currency, mini-games and cosmetics do not affect iMafia ranking or fixed place prizes.

This is a pre-season model. It proves that the formulas and planned budgets reconcile; it does not prove actual demand, player attendance or average forecast accuracy. After the first 2–3 evenings, review: median CR/EX balances, percent of players who can afford each price tier, purchased item distribution, forecast reward/forecast ratio, source-to-sink ratio, and bonus-score spread. Change prices or rates only with a versioned economy update, not by silently changing a live season.

## 8. Approval and rollout

Economy v1.0 is stored as DRAFT. The admin interface requires the Activity Score to be approved before economy approval, and requires both before prediction approval. Mini-game XP and game-based CR/XP are gated on economy approval. Store catalogue entries remain disabled until separately enabled.

Apply migration 004 only after reviewing migrations 001–003 and validating the schema in a staging Neon branch. No migration, approval, deployment or season activation is performed merely by adding this model.
