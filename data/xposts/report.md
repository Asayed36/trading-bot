# X posts and the pump.fun launches after them

Measurement only (screener/xposts_report.py), written 2026-11-28 07:22 UTC, the last 7 days. For each post, the new launches in the 10 minutes after it whose name or symbol matches a word of the post. Price moves are from the first recorded price (5 s after the launch) and exist only for the launches the launch recorder followed (qualified launches and a 2% sample); a match is not a cause.

252 post(s), 150 matching launch(es).

## Ticker mentions

Recording only (screener/xmentions.py), the last 7 days. Cashtags, Solana and EVM addresses in the saved posts (at most 5 a post), each looked up once on DexScreener. Changes are from the price at the first check (not the post's own time); BTC is over the same real times, from the once-a-minute price log. "large": BTC, ETH, SOL, BNB, XRP, DOGE or above $5 billion. A handful of mentions says nothing yet; a mention is not a cause.

17 mention(s) in 14 post(s): 17 identified.

| Account | Coins | Mentions | 5m coin avg / median (n) | 5m BTC avg / median | 15m coin avg / median (n) | 15m BTC avg / median | 60m coin avg / median (n) | 60m BTC avg / median |
|---|---|---|---|---|---|---|---|---|
| @blknoiz06 | small | 1 | –, 1 missed | – | –, 1 missed | – | –, 1 missed | – |
| @cz_binance | small | 1 | +0.00% / +0.00% (1) | +0.07% / +0.07% | +0.00% / +0.00% (1) | +0.13% / +0.13% | +0.00% / +0.00% (1) | +0.81% / +0.81% |
| @justinsuntron | small | 1 | +0.00% / +0.00% (1) | -0.21% / -0.21% | +0.00% / +0.00% (1) | -0.53% / -0.53% | +0.00% / +0.00% (1) | -0.08% / -0.08% |
| @saylor | large | 2 | +0.00% / +0.00% (2) | +0.14% / +0.14% | +0.00% / +0.00% (2) | +0.43% / +0.43% | +0.00% / +0.00% (2) | +1.51% / +1.51% |
| @saylor | small | 12 | -0.01% / +0.00% (12) | -0.02% / -0.05% | -0.01% / +0.00% (12) | -0.03% / -0.03% | +0.61% / +0.00% (12) | +0.73% / +0.06% |

Latest mentions (newest first; candidates = different tokens with that symbol in DexScreener's search answer, so more than 1 means the ticker is ambiguous):

| Posted (UTC) | Account | Mention | Coin | Candidates | Large | First check after | 1 h change at first check | 5m | 15m | 60m | 24h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-27 14:43 | @saylor | $STRC | STRC (base) | 4 | no | 0.6 min | – | +0.0% | +0.0% | +0.0% | – |
| 2026-11-27 02:32 | @justinsuntron | $USDD | USDD (solana) | 10 | no | 1.8 min | – | +0.0% | +0.0% | +0.0% | +0.0% |
| 2026-11-26 13:15 | @saylor | $TSLA | TSLA (solana) | 5 | no | 1.2 min | +0.1% | +0.0% | +0.0% | -0.3% | +1.8% |
| 2026-11-26 13:15 | @saylor | $MSTR | MSTR (robinhood) | 9 | no | 1.2 min | +0.1% | -0.2% | -0.2% | -0.0% | +2.3% |
| 2026-11-25 14:53 | @saylor | $STRC | STRC (base) | 3 | no | 1.1 min | – | +0.0% | +0.0% | +0.0% | +1.4% |
| 2026-11-25 12:57 | @saylor | $STRC | STRC (base) | 3 | no | 1.0 min | – | +0.0% | +0.0% | +0.0% | +1.4% |
| 2026-11-25 00:46 | @saylor | $STRC | STRC (base) | 3 | no | 1.8 min | – | +0.0% | +0.0% | +0.0% | +1.4% |
| 2026-11-24 21:31 | @saylor | $STRC | STRC (base) | 3 | no | 0.4 min | – | +0.0% | +0.0% | +0.0% | missed |
| 2026-11-24 13:31 | @cz_binance | $SPCX | SPCX (solana) | 13 | no | 0.7 min | – | +0.0% | +0.0% | +0.0% | +0.0% |
| 2026-11-23 19:36 | @blknoiz06 | $NVDA | NVDA (robinhood) | 7 | no | 265.4 min | -0.8% | missed | missed | missed | -7.6% |
| 2026-11-23 17:02 | @saylor | $STRC | STRC (base) | 5 | no | 2.1 min | – | +0.0% | +0.0% | +0.0% | -0.1% |
| 2026-11-23 15:09 | @saylor | $BTC | BTC (solana) | 28 | yes | 0.6 min | – | +0.0% | +0.0% | +0.0% | +0.0% |
| 2026-11-23 13:02 | @saylor | $STRC | STRC (base) | 4 | no | 1.9 min | – | +0.0% | +0.0% | +0.5% | +0.4% |
| 2026-11-23 13:02 | @saylor | $MSTR | MSTR (robinhood) | 9 | no | 1.9 min | -0.7% | +0.2% | +0.2% | +2.6% | -2.6% |
| 2026-11-23 13:02 | @saylor | $BTC | BTC (solana) | 28 | yes | 1.9 min | – | +0.0% | +0.0% | +0.0% | +0.0% |
| 2026-11-22 22:17 | @saylor | $MSTR | MSTR (robinhood) | 7 | no | 2.4 min | +0.1% | -0.2% | -0.2% | -0.2% | +3.0% |
| 2026-11-21 13:01 | @saylor | $STRC | STRC (base) | 2 | no | 1.2 min | – | +0.0% | +0.0% | +4.8% | +5.3% |

## Posts seen late

The last 7 days: per account, the posts saved more than 3 minutes after they were posted, and why; and the rounds (one every 120 s) it was not asked, and why. An account skipped for the per-account limit starts again from that moment the next day: the posts it made meanwhile are not read at all, so they are not in the late count. 'not recorded': saved before the reasons were recorded (2026-11-20).

| Account | Posts saved | Seen late | Why late | Rounds not asked (why) |
|---|---|---|---|---|
| @a1lon9 | 3 | 0 | – | 1: 1 X error or pause |
| @blknoiz06 | 32 | 22 | 17 other, 5 not recorded | 2629: 2629 per-account limit |
| @cz_binance | 17 | 0 | – | 80: 80 per-account limit |
| @elonmusk | 48 | 31 | 26 other, 5 not recorded | 3650: 3650 per-account limit |
| @justinsuntron | 44 | 14 | 9 other, 5 not recorded | 2429: 2429 per-account limit |
| @mrbeast | 4 | 0 | – | – |
| @muststopmurad | 34 | 0 | – | 27: 26 per-account limit, 1 X error or pause |
| @pumpfun | 21 | 7 | 3 other, 4 not recorded | 379: 378 per-account limit, 1 X error or pause |
| @realdonaldtrump | 0 | 0 | – | 1: 1 X error or pause |
| @saylor | 20 | 1 | 1 other | 207: 207 per-account limit |
| @toly | 49 | 40 | 35 other, 5 not recorded | 4871: 4871 per-account limit |
| @vitalikbuterin | 4 | 0 | – | – |

## Posts and the launches after them

## @toly 2026-11-21 00:11:23 UTC (post 2123932250308039087)
> 😭😭😭 https://t.co/gshO7b337l

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-21 02:10:50 UTC (post 2123962308384751920)
> SPX6900 WILL BE EVERYWHERE. AND THE WORLD WILL READJUST. https://t.co/mOocrmoHEs

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 02:41:53 UTC (post 2123970124898275829)
> zcash nuking is a leading indicator for the israel-iran conflict

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 02:42:21 UTC (post 2123970241549959423)
> geopolitics with ansem https://t.co/AEDdnTuXPJ

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 02:43:08 UTC (post 2123970436090491063)
> i mean how does this thing go from strongest asset in the whole space to limpdick wet toilet paper jeez louise

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| LIMPDICK | limpdick | +0%, no liq @1.4m | -1%, no liq @5.7m | -12%, no liq @15.3m | -12%, no liq @60.6m | – | no |
| TOILETPAPER | jeez, limpdick, paper, toilet | +0%, no liq @1.7m | +1%, no liq @6.0m | +1%, no liq @15.7m | -1%, no liq @61.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 23 s | LIMPDICK | limpdick | limpdick | price not recorded |  |  |  |  |
| 67 s | TOILETPAPER | Limpdick Wet Toilet Paper Jeez | jeez, limpdick, paper, toilet | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-21 05:35:00 UTC (post 2124013687556165828)
> 对于近期梦女针对我的持续骚扰和不实信息，通过恶意炒作获取流量，我此前没有过多回应，是希望保留善意，避免占用公共讨论的空间。 但善意和克制，也需要得到基本的尊重。

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-21 06:34:43 UTC (post 2124028719190749681)
> Playing GTA VI with Telepathy https://t.co/Q8fQUHjaWb

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-21 07:06:08 UTC (post 2124036622987710730)
> $1M each. Proud to back great math. 🧮 https://t.co/sMIFCrcjsM

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-21 09:39:06 UTC (post 2124075117861085388)
> 孙宇晨奖将为黎曼猜想的两项核心成果颁发 100 万美元奖励！ https://t.co/p3r6C6yhNH

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-21 10:38:18 UTC (post 2124090018725794035)
> This is when all the generational wealth in Crypto is made. It’s just collected many years later. Buy and Hold.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| BAH | hold | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 25 s | BAH | Buy And Hold | hold | price not recorded |  |  |  |  |

## @saylor 2026-11-21 13:01:01 UTC (post 2124125931786953142)
> Every day we Stretch. $STRC https://t.co/9LKnZRIPiZ

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-21 14:36:03 UTC (post 2124149847754441089)
> Being in Crypto and on Crypto Twitter in 2027 and NOT being a part of such an EARLY stage of SPX6900 will eventually be a HUGE regret for th

No matching launch in the next 10 minutes.

## @toly 2026-11-21 14:45:56 UTC (post 2124152336612536558)
> An nft collection for every 1 second clip of the “real show”. Each nft pays for the cycles needed to generate content. Whoever owns it can t

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 294 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |
| 296 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |
| 296 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |
| 336 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |
| 336 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |
| 336 s | ape | ITS REAL BTW | real | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-21 15:38:53 UTC (post 2124165661417250819)
> Over $1,000,000,000 in perps volume has been traded on the Pumpfun app! Get involved with the $1M Perps Open trading competition, live now 👇

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| OPEN | open, perps | +0%, no liq @1.6m | +0%, no liq @6.0m | +0%, no liq @15.7m | +0%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 6 s | OPEN | $1M Perps Open | open, perps | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-21 15:38:54 UTC (post 2124165667288961325)
> Learn more about the $1M Perps Open, ends December 4: https://t.co/tGpBD9tuvN

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 5 s | OPEN | $1M Perps Open | open, perps | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-21 15:38:56 UTC (post 2124165673102270971)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIEEj4 does not operate. https://t.co/WWU97JhnqK is an app

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 3 s | OPEN | $1M Perps Open | perps | price not recorded |  |  |  |  |

## @toly 2026-11-21 16:22:17 UTC (post 2124176582931775909)
> Breaking: Jensen Huang reportedly said, “orange you glad I didn’t say banana”.

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 2 s | ORANGE | orange | orange | price not recorded |  |  |  |  |
| 4 s | banana | banana | banana | -0% | -0% | -0% | -0% | +79% (0 s) |
| 47 s | ORANGE | orange | orange | price not recorded |  |  |  |  |
| 81 s | banana | banana | banana | +0% | +203% | +203% | +203% | +223% (142 s) |
| 479 s | JENBACK | Jensen Back Again | jensen | -9% | -9% | -24% | -24% | +10% (34 s) |

## @toly 2026-11-21 16:23:36 UTC (post 2124176913719845135)
> 👑👑👑 https://t.co/wxufKGWw5d

No matching launch in the next 10 minutes.

## @toly 2026-11-21 16:24:25 UTC (post 2124177120482251204)
> 👑👑👑 https://t.co/8E6bQgCivn

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-21 16:45:50 UTC (post 2124182508271018258)
> The AGI buildout is the "Hail Mary Play" of the entire Hyper-Financialized and Under-Industrialized Western Civilization An all or nothing p

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-21 18:19:48 UTC (post 2124206158848430270)
> Mantle is live on the Pumpfun app Trade and callout tokens in the Mantle ecosystem to earn Callout Rewards Welcome to the Pumpfun app, @Mant

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 100 s | Mantle | Mantle | mantle | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-21 19:34:16 UTC (post 2124224897505177780)
> The longer the Reaccumulation, the bigger the future Parabola.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| PARABOLA | parabola | +0%, no liq @1.1m | -20%, no liq @5.5m | -20%, no liq @15.6m | -20%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 173 s | PARABOLA | The Parabola | parabola | -46% | -57% | -57% | -57% | +25% (2 s) |

## @elonmusk 2026-11-21 20:26:59 UTC (post 2124238164512714925)
> In FSD V15, the Tesla AI computer re-renders reality with chevrons in the sky for turns like a video game. You can tap any point on the real

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 180 s | GTA | Grand Tesla Auto | tesla | -45% | -45% | -45% | -45% | +0% (5 s) |

## @elonmusk 2026-11-21 20:27:19 UTC (post 2124238249686159590)
> It’s like GTA https://t.co/H2H9tjTStt

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 160 s | GTA | Grand Tesla Auto | gta | -45% | -45% | -45% | -45% | +0% (5 s) |
| 176 s | GTA | Great Times Ahead | gta | +41% | +41% | -74% | -74% | +41% (22 s) |

## @elonmusk 2026-11-21 20:40:31 UTC (post 2124241570451054609)
> It’s high time we probed Uranus again! Much better images are needed (actually).

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 25 s | URANUSCOIN | Uranus Coin | uranus | price not recorded |  |  |  |  |
| 123 s | URANUS | UranusCoin | uranus | price not recorded |  |  |  |  |
| 173 s | UI | Uranus Inu | uranus | price not recorded |  |  |  |  |
| 179 s | URANUS | URANUS | uranus | price not recorded |  |  |  |  |
| 195 s | URANUS | UranusCoin | uranus | price not recorded |  |  |  |  |
| 302 s | URANUS | URANUS | uranus | price not recorded |  |  |  |  |
| 306 s | URANUS | Uranus | uranus | price not recorded |  |  |  |  |
| 312 s | URANUS | URANUS | uranus | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-21 21:14:57 UTC (post 2124250234457063616)
> New perps execution tools on the Pumpfun app! - TWAP: break big orders into small fills over time - Stack limit orders: multiple orders on o

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 292 s | TWAP | TWAP | twap | price not recorded |  |  |  |  |
| 300 s | TWAP | TWAP | twap | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-21 21:14:58 UTC (post 2124250239934849163)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 21:45:33 UTC (post 2124257937887826364)
> ex. $100k $BTC short on 10x leverage paid ~$7.8k &amp; profit from trade was ~$135k realized PNL $50k $SOL short on 20x leverage paid ~$6.4k

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 468 s | BTC | Big Three Coin | btc | price not recorded |  |  |  |  |

## @toly 2026-11-21 21:50:32 UTC (post 2124259190764191984)
> 👑👑👑 https://t.co/HRh8H2SQgn

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 22:24:49 UTC (post 2124267820049674564)
> one of my best posts tbh https://t.co/4qWQgfeqJb

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 22:31:05 UTC (post 2124269396155682940)
> think schoen is one of the best trenchers on this app, always very early to plays and one of the most active traders who is always sharing w

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-21 22:35:11 UTC (post 2124270426402836626)
> This is real-time AI video generation (no gaming engine!) using just half of one AI4 TRIP accelerator. Let that sink in … https://t.co/ieASM

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 357 s | ACC | AI4 TRIP Accelerator | accelerator, trip | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-21 22:43:06 UTC (post 2124272421314113667)
> https://t.co/0PcrroCra6

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-21 23:02:34 UTC (post 2124277317782450670)
> long superintelligence long open source models long open financial networks https://t.co/SsA144Z7e2

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 23 s | S | Superintelligence | superintelligence | price not recorded |  |  |  |  |
| 39 s | S | Superintelligence | superintelligence | price not recorded |  |  |  |  |

## @elonmusk 2026-11-21 23:16:03 UTC (post 2124280710747840889)
> Give Grok @Bot your hardest tasks https://t.co/KEa57ff3ux

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-22 00:11:51 UTC (post 2124294755316310346)
> Tesla FSD V15 is a banger release! Completely new architecture that deserves being called “super” intelligence, as it drives better than hum

No matching launch in the next 10 minutes.

## @toly 2026-11-22 00:45:26 UTC (post 2124303204079091790)
> 👑👑👑 https://t.co/5WxTDIhXFB

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 01:02:20 UTC (post 2124307459695075399)
> Why Tokenized Movements are the Future of Crypto Join our Spaces Tomorrow Sunday (Nov 22) 2pm EST / 7pm UTC Set your reminder below👇 https:/

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-22 03:27:01 UTC (post 2124343870645260476)
> wyd

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| wyd | wyd | +0%, no liq @1.1m | +0%, no liq @5.4m | -17%, no liq @15.1m | -17%, no liq @60.1m | – | no |
| wyd | wyd | +0%, no liq @1.1m | -1%, no liq @5.4m | -1%, no liq @15.1m | -1%, no liq @60.1m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 70 s | wyd | wyd | wyd | price not recorded |  |  |  |  |
| 71 s | wyd | wyd | wyd | +0% | -1% | -1% | -1% | +42% (0 s) |

## @justinsuntron 2026-11-22 05:35:35 UTC (post 2124376223275180196)
> 只是把自己的本分做好 https://t.co/FLcj2z2Dn5

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-22 05:56:38 UTC (post 2124381522845487520)
> 我对于购买字节老股有兴趣，买 5% 以下，需要的可以找我。

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-22 05:58:24 UTC (post 2124381965877199186)
> 减脂的时候，高糖高油高盐的食物要极力避开，一口不吃，就能夺回身体的主动权。 精神上也有"高糖高油高盐"，就是抖音、红果、游戏这些精加工的内容。把它们删掉，就能夺回注意力。 长期高糖高油高盐，身体垮了，一辈子一事无成。天天抖音、红果、游戏，注意力垮了，一辈子浑浑噩噩。

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-22 06:01:09 UTC (post 2124382659191447598)
> @AlanShao111 可以认真研究一下人每天精神上服用大量高糖高油高盐产品，会对我们的身体造成多大损害的。

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-22 06:17:09 UTC (post 2124386686188900504)
> 体重有没有超标，可以参考

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-22 07:33:13 UTC (post 2124405826018500745)
> Quod probatur, solvitur. https://t.co/HVKeqEXwIZ

No matching launch in the next 10 minutes.

## @MrBeast 2026-11-22 11:03:59 UTC (post 2124458867463516218)
> Seems like you guys are enjoying them 🙏🏻 https://t.co/bb9pQp9p7q

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 11:28:27 UTC (post 2124465024421040161)
> Only if you build a Community where most people are prepared to go hard for the next 10+ years will the coin go into Trillions. Must people 

No matching launch in the next 10 minutes.

## @saylor 2026-11-22 13:11:04 UTC (post 2124490849811857441)
> The dots aren’t done. https://t.co/y92ITprFKE

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 14:16:42 UTC (post 2124507367702397407)
> spx6900 attracts the NON-materialistic and NON-money-hungry people, that's why it will thrive for 10+ years and will go to many many Trillio

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 203 s | MCAT MONEY | Moon Cat MONEY | money | -83% | -99% | -99% | -99% | +42% (7 s) |

## @blknoiz06 2026-11-22 15:17:11 UTC (post 2124522587875066344)
> how much has ai improved your life over past 5 years on a scale from 1 to 10

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 217 s | trench | trench life | life | -94% | -94% | -94% | -94% | +122% (16 s) |

## @blknoiz06 2026-11-22 15:19:58 UTC (post 2124523290228064457)
> can someone point me to tradfi land so i can follow the stocks guys i need to see how they are responding to this

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 16:33:15 UTC (post 2124541733178331602)
> The reason why it’s always the Holders who end up winning massively, and not the traders is because: Trading requires you to make a million 

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-22 16:58:06 UTC (post 2124547985568907606)
> on September 24, i discussed with @rasmr_eth why university matters more in the age of AI as AI makes intelligence widely accessible, social

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 12 s | EI | Emotional Intelligence | emotional, intelligence | price not recorded |  |  |  |  |
| 52 s | EI | Emotional Inu | emotional | price not recorded |  |  |  |  |
| 57 s | EI | Emotional Inu | emotional | price not recorded |  |  |  |  |
| 57 s | EI | Emotional Inu | emotional | price not recorded |  |  |  |  |
| 63 s | EI | Emotional Intelligence | emotional, intelligence | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-22 18:54:03 UTC (post 2124577163949334667)
> forgot i had two tickets to this eagles game today if anybody is tailgating or at xfinity rn &amp; wants them can transfer them to you dm ht

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 19:00:57 UTC (post 2124578901154218041)
> https://t.co/pM5jna1tTp

No matching launch in the next 10 minutes.

## @saylor 2026-11-22 19:09:34 UTC (post 2124581068053631407)
> During the Bitcoin Standard Era, Digital Capital outperformed the Equity, Metallic, Real Estate, and Debt Capital benchmarks shown. https://

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-22 19:09:44 UTC (post 2124581113540526316)
> the end state of every man is to hoop &amp; post https://t.co/QEEJPrGAVr

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-22 19:39:11 UTC (post 2124588521507962895)
> MORE Perps upgrades on the Pumpfun app! - Social lines: see other traders entries, TP/SL and liquidations - Bubbles: see buys and sells from

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| CHART | chart | +0%, no liq @1.1m | +0%, no liq @5.3m | +0%, no liq @16.0m | +0%, no liq @60.9m | – | no |
| Bubbles | bubbles | +0%, no liq @1.0m | -5%, no liq @5.3m | -5%, no liq @15.9m | -5%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 44 s | CHART | Chart Trading | chart | price not recorded |  |  |  |  |
| 47 s | Bubbles | Bubbles | bubbles | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-22 19:39:12 UTC (post 2124588526448853382)
> The $1M Perps Open is live until Dec 4, 16:00 UTC. Join now: https://t.co/P2oCUKFWOO

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-22 19:39:13 UTC (post 2124588530928374045)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-22 21:02:21 UTC (post 2124609453274108083)
> 360 degree vision that never tires https://t.co/uxbPR87SQE

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 441 s | 360 | 360 degree vision | degree, vision | +0% | -58% | -58% | -59% | +0% (5 s) |

## @elonmusk 2026-11-22 21:22:58 UTC (post 2124614639409606954)
> Would this be the wrong note upon which to suggest using Grok Bot? https://t.co/qfYPtHSaRV

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-22 21:42:40 UTC (post 2124619599882920139)
> Consciousness is either an illusion or ubiquitous on a gradient. Difficult to argue that carbon is conscious, but silicon is not.

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 44 s | CI | carbon inu | carbon | price not recorded |  |  |  |  |
| 187 s | CI | Conscious Inu | conscious | price not recorded |  |  |  |  |
| 232 s | CI | Conscious Inu | conscious | price not recorded |  |  |  |  |

## @elonmusk 2026-11-22 21:52:12 UTC (post 2124621998521212940)
> Starlink helps kids with education https://t.co/vUuGt09nTL

No matching launch in the next 10 minutes.

## @toly 2026-11-22 21:55:42 UTC (post 2124622877106532563)
> 👑👑👑 https://t.co/0HRZfuQjmn

No matching launch in the next 10 minutes.

## @toly 2026-11-22 21:58:37 UTC (post 2124623612628050065)
> 👑👑👑 https://t.co/KaSrsxrmAZ

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-22 22:01:12 UTC (post 2124624263214662097)
> The small details are so good https://t.co/teplwYZ9k3

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 219 s | DTLS | Details Matter | details | price not recorded |  |  |  |  |

## @toly 2026-11-22 22:05:25 UTC (post 2124625324122271966)
> 👑👑👑 https://t.co/w8fSIWOUEv

No matching launch in the next 10 minutes.

## @toly 2026-11-22 22:15:54 UTC (post 2124627962826018906)
> 👑👑👑 https://t.co/5hLD51riXI

No matching launch in the next 10 minutes.

## @saylor 2026-11-22 22:17:51 UTC (post 2124628454540759493)
> Digital Equity builds on Digital Capital. During the Bitcoin Standard Era, $MSTR delivered 34% annualized returns, outperforming Bitcoin and

No matching launch in the next 10 minutes.

## @toly 2026-11-22 22:44:09 UTC (post 2124635069717618701)
> 🤌🤌🤌 https://t.co/GbOP56bBy6

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-22 23:04:08 UTC (post 2124640102173593898)
> SPX6900 is the next Bitcoin. It has a different shape, and a different flavor, but at its core, it is accomplishing the same thing — Wealth 

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 00:06:59 UTC (post 2124655915680895186)
> how we feeling lads

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-23 01:20:01 UTC (post 2124674295246811586)
> 😂 https://t.co/YcbC1FArSP

No matching launch in the next 10 minutes.

## @saylor 2026-11-23 02:07:36 UTC (post 2124686272673595686)
> Strategy engineers volatility to create a spectrum of financial products for equity, derivatives, commodity, and credit investors. https://t

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-23 02:29:04 UTC (post 2124691673058070800)
> 🤣 or maybe it will be the other way around, ie, the FUD will be stopped (mostly) by a green candle. https://t.co/e71ruhdZ0f

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| GC | candle, green | +0%, no liq @1.7m | +0%, no liq @6.0m | +0%, no liq @15.5m | +0%, no liq @60.6m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 232 s | GC | Green Candle | candle, green | price not recorded |  |  |  |  |

## @cz_binance 2026-11-23 02:56:56 UTC (post 2124698685116383430)
> Used Grok Bot to clean up inactive and abusive accounts I follow. Ask it to keep constructive criticism. Not sure how well it worked. "AI di

No matching launch in the next 10 minutes.

## @toly 2026-11-23 03:19:51 UTC (post 2124704453341446570)
> 🐐🐐🐐 https://t.co/iAe3Qu48xN

No matching launch in the next 10 minutes.

## @toly 2026-11-23 03:21:17 UTC (post 2124704814894612647)
> 🧠🧠🧠 https://t.co/FtZpFvAzj3

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-23 04:12:38 UTC (post 2124717736693830006)
> Agree with @elonmusk. Super intelligence is doing big math now. Riemann award is open. Who’s next? 👇 https://t.co/CmjxzLYqRN https://t.co/SG

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| MI | math | +0%, no liq @1.8m | +0%, no liq @6.1m | +0%, no liq @15.7m | +0%, no liq @60.8m | – | no |
| AI | intelligence | +0%, no liq @1.3m | -39%, no liq @5.6m | -31%, no liq @15.3m | -43%, no liq @60.3m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 210 s | MI | MATH  INU | math | price not recorded |  |  |  |  |
| 494 s | AI | Alien intelligence | intelligence | -6% | -42% | -34% | -35% | +0% (2 s) |

## @justinsuntron 2026-11-23 07:37:03 UTC (post 2124769179052196211)
> few https://t.co/Y8w98RoIFX

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-23 11:04:51 UTC (post 2124821475571970159)
> Times like these are great because they allow the Strongest Crypto Communities to stand out from everything else. Pay attention to the Commu

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| $NB | bull | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 586 s | $NB | NEON BULL | bull | price not recorded |  |  |  |  |

## @saylor 2026-11-23 13:02:23 UTC (post 2124851054814883872)
> Strategy has acquired 457 $BTC and repurchased $212M of $STRC. We increased our Digital Credit Securities Repurchase Program by $1B and real

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| HOLD | hold | +0%, no liq @1.2m | +0%, no liq @5.5m | +0%, no liq @15.1m | +0%, no liq @60.9m | – | no |
| HOLD | hold | +0%, no liq @1.2m | +0%, no liq @5.4m | +0%, no liq @15.0m | +0%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 60 s | HOLD | HYPERHOLD | hold | +6% | +6% | +6% | +6% | +24% (16 s) |
| 129 s | HOLD | HYPERHOLD | hold | -85% | -85% | -85% | -85% | +46% (0 s) |

## @saylor 2026-11-23 13:02:24 UTC (post 2124851056488202250)
> We have reduced credit outstanding by $2.9B in recent months, lowering annual dividends by $353M. Our USD Duration is now 3.4 years, so we r

No matching launch in the next 10 minutes.

## @saylor 2026-11-23 13:02:24 UTC (post 2124851058560385207)
> Our trades increased Net Reserve by $183M and Net BPS by 6 sats/share before preferred dividends, measured at our average BTC purchase price

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-23 14:06:12 UTC (post 2124867114465124495)
> SPX6900 is the reincarnation of early BTC.

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-23 14:20:41 UTC (post 2124870759147606082)
> welcome back! https://t.co/ppJydcfvYj

No matching launch in the next 10 minutes.

## @saylor 2026-11-23 15:09:35 UTC (post 2124883063096164450)
> Our trades accreted Net BPS in each of the last 13 weeks. Cumulatively, we increased Net BPS by 584 sats/share and generated a Net BTC Gain 

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| Btc | btc | +0%, no liq @1.3m | +0%, no liq @5.6m | +0%, no liq @15.2m | +0%, no liq @60.4m | – | no |
| Btc | btc | +0%, no liq @1.2m | +0%, no liq @5.5m | +0%, no liq @15.2m | +0%, no liq @60.3m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 465 s | Btc | Gcoin | btc | price not recorded |  |  |  |  |
| 535 s | Btc | Gcoin | btc | price not recorded |  |  |  |  |

## @cz_binance 2026-11-23 16:05:27 UTC (post 2124897123296481428)
> Glad to see @JensenHuang back. 👏 https://t.co/WrUjvmEyVi

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-23 16:32:25 UTC (post 2124903908086800672)
> People always underestimate how quickly the markets can turn. Especially the Crypto market. You blink and it will have begun. That’s why HOD

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| JacketMarkets | markets | +0%, no liq @1.3m | +0%, no liq @5.6m | -32%, no liq @15.5m | -32%, no liq @60.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 460 s | JacketMarkets | Jacket Markets | markets | -6% | -19% | -41% | -41% | +5% (1 s) |

## @saylor 2026-11-23 17:02:03 UTC (post 2124911367786295660)
> Over the past 13 weeks, our $STRC buybacks and related capital markets activity have reduced our Annual Int + Div by $296M and added $1.81B 

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-23 17:28:06 UTC (post 2124917923391443211)
> Those who violate the law on this platform WILL be prosecuted, WHEREVER they may be in the world. https://t.co/OmFAlwsmh4

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 114 s | cuted | prosecuted | prosecuted | +0% | +0% | +0% | +0% | +0% (0 s) |
| 114 s | cuted | prosecuted | prosecuted | price not recorded |  |  |  |  |

## @elonmusk 2026-11-23 17:30:38 UTC (post 2124918561617694750)
> True https://t.co/8jbmsDPCRi

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-23 19:07:04 UTC (post 2124942828274925651)
> Everyone I know at Nvidia wanted Jensen back and it shows https://t.co/JgdlBhD0Yi

No matching launch in the next 10 minutes.

## @saylor 2026-11-23 19:07:21 UTC (post 2124942899356082554)
> We don't need a ₿ailout. https://t.co/0bu5b64nmu

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-23 19:13:35 UTC (post 2124944467119747335)
> Beautiful shot by Andrew McCarthy https://t.co/nUJRMXQ9yR

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 19:34:43 UTC (post 2124949785924997418)
> ok nvda +30% pearl +20% and every other coin full retraced the pump we have some theorycrafting to do

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 19:36:48 UTC (post 2124950312997839314)
> if togi wouldve been 10x long his $600k on hyperliquid $NVDA perps on @tradexyz instead of yolo'ing options after market close he would've m

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 19:49:02 UTC (post 2124953388668408046)
> actually in disbelief at how weak bitcoin is

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 19:56:15 UTC (post 2124955207574667393)
> Changing your mind at the right time isn't a flaw in the job. It is the job. https://t.co/RggLwXNfRt

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-23 20:35:08 UTC (post 2124964992277446975)
> In my 14 years in Crypto, I've only ever seen this kind of thing happen with one other asset - Bitcoin. Now it's happening with SPX6900 Don'

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-23 21:14:40 UTC (post 2124974939728199879)
> X going hard on video https://t.co/F9XDAdAteY

No matching launch in the next 10 minutes.

## @toly 2026-11-23 22:35:50 UTC (post 2124995367024607482)
> 👑👑👑 Breakpoint is a party, but it’s real purpose has always been to generate business leads for ecosystem companies. https://t.co/kAuV4TW6mX

No matching launch in the next 10 minutes.

## @toly 2026-11-23 22:45:14 UTC (post 2124997731848745252)
> I bet I’d be a top 3 Nvidia ceo.

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 93 s | TOLY | The Nvidia Ceo | nvidia | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-23 22:45:24 UTC (post 2124997775737946168)
> Sui is live on the Pumpfun app Trade and callout tokens in the Sui ecosystem to earn Callout Rewards! Welcome to the Pumpfun app, @SuiNetwor

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SUI | sui | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 144 s | SUI | SUI | sui | price not recorded |  |  |  |  |

## @toly 2026-11-23 23:31:36 UTC (post 2125009398628331805)
> 1) what https://t.co/Q2JrXYl0Fp

No matching launch in the next 10 minutes.

## @toly 2026-11-23 23:36:03 UTC (post 2125010518851342472)
> 😭😭😭 https://t.co/6vzHzGNDv4

No matching launch in the next 10 minutes.

## @toly 2026-11-23 23:42:31 UTC (post 2125012147310883216)
> Thank the Lord https://t.co/p8nbRq3SIF

No matching launch in the next 10 minutes.

## @toly 2026-11-24 00:07:09 UTC (post 2125018347284865262)
> Do you know the difference between vnp and np? No, do you? No? https://t.co/totw833iR3

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 01:21:49 UTC (post 2125037136802107486)
> few https://t.co/LgnLgWknJP

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-24 01:52:50 UTC (post 2125044944658423857)
> 📍 https://t.co/eB8WtrqrMm

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-24 01:53:17 UTC (post 2125045055803290032)
> bros i am frightened to bid this

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 03:02:14 UTC (post 2125062408024805752)
> TRON in 🇹🇭 https://t.co/jsbbAlDJh0

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-24 04:18:30 UTC (post 2125081599280582807)
> lmfao https://t.co/BotoJK0g0U

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-24 04:34:23 UTC (post 2125085599388545151)
> 🙏 https://t.co/lsFBz9JJH0

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-24 04:40:28 UTC (post 2125087128606425372)
> Even Laura Shin (who usually portraits me negatively) can't stand it anymore. 🤣🙏 https://t.co/6s7MwxLjxu

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 05:15:00 UTC (post 2125095818654892319)
> Solve it. Prove it. Submit it. 👉 https://t.co/XltLa5foTY

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 06:57:41 UTC (post 2125121661313941844)
> Users should always come first. You deserve a clear explanation and fair treatment. If similar restrictions can be resolved for users who in

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 07:30:00 UTC (post 2125129795533168750)
> A walkthrough of TRC-6909 on TRON with OpenZeppelin. 🔻 https://t.co/oIVYpKsIqh

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-24 10:44:51 UTC (post 2125178828943184363)
> Bullseye https://t.co/69ar1yur6u

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| Bullseye | bullseye | +0%, no liq @1.9m | +0%, no liq @5.1m | +0%, no liq @15.0m | +0%, no liq @60.5m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 413 s | Bullseye | Bullseye | bullseye | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-24 10:50:57 UTC (post 2125180366243917975)
> Trust is the scarcest and the most valuable thing in the world. It takes many years to build. The crypto community that is successful at cul

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| Trust | trust | missed | missed | missed | missed | – | no |
| TRUST | trust | +0%, no liq @1.2m | -17%, no liq @5.5m | -22%, no liq @15.5m | -22%, no liq @61.0m | – | no |
| TRUST | trust | missed | missed | missed | missed | – | no |
| TRUST | trust | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 9 s | Trust | Trust | trust | price not recorded |  |  |  |  |
| 20 s | TRUST | trust coin | trust | price not recorded |  |  |  |  |
| 22 s | TRUST | trust coin | trust | price not recorded |  |  |  |  |
| 55 s | TRUST | trust coin | trust | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-24 10:59:11 UTC (post 2125182437063790806)
> pump wallet is hacked, trying to figure out how, believe its unauthorized access to my bullpen profile somehow which had the sol priv key im

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 292 s | ANSEM | he will make new wallet | wallet | price not recorded |  |  |  |  |
| 293 s | ANSEM | he will make new wallet | wallet | price not recorded |  |  |  |  |
| 294 s | ANSEM | he will make new wallet | wallet | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-24 11:58:11 UTC (post 2125197283977510996)
> Feel free to mint your ETH and BTC to stablecoin via USDD protocol https://t.co/X3MAAXRcah

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-24 12:57:30 UTC (post 2125212213493596562)
> https://t.co/VF8MRtbXSr

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-24 13:17:39 UTC (post 2125217281349472651)
> 👇 This is from a guy who don't like me that much 😂, but definitely in-the-know. Wei was CFO of Binance who handled and pushed for the invest

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-24 13:31:32 UTC (post 2125220776316133514)
> Woah... "You know that Binance’s $SPCX perpetual futures traded 1.957 billion USDT on November 23, but I bet you didn’t know that already ac

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 13:38:50 UTC (post 2125222613006049647)
> Stablecoins and #JustinSunPrize on the agenda with @ucblockchain. https://t.co/oaeSIqHJGE

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 13:41:52 UTC (post 2125223375438323902)
> Looking forward to joining @StaniKulechov to talk about the future of finance. See you soon. 👋 https://t.co/pLkvjNW3ve

No matching launch in the next 10 minutes.

## @saylor 2026-11-24 14:01:30 UTC (post 2125228316986646901)
> Bitcoin is Digital Capital. CFTC staff now recognize that U.S. derivatives exchanges and clearinghouses can count Bitcoin toward their opera

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-24 15:01:48 UTC (post 2125243493446816171)
> "Imagine someone told you about spx6900 in 2027” Will be the same as "Imagine someone told you about bitcoin in 2011” Mark my words.

No matching launch in the next 10 minutes.

## @MrBeast 2026-11-24 15:44:31 UTC (post 2125254243305087198)
> I NEED the best Shorts creatives on the planet! Click the link, pick a few of my Shorts, and tell me on video what worked and what you'd cha

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-24 17:10:41 UTC (post 2125275928838205744)
> We don't need to attack others while they are down. We just need to persist with our own cause.

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-24 17:11:11 UTC (post 2125276052964753727)
> 巴菲特说的好，短期是选美赛，长期是称重机，TRX是最美的称重机😄 https://t.co/lCytqppjb7

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-24 18:08:17 UTC (post 2125290423304479017)
> All detailed in my book, Freedom of Money.

No matching launch in the next 10 minutes.

## @toly 2026-11-24 19:30:35 UTC (post 2125311136182722704)
> 👑👑👑 https://t.co/64V9mWpaGH

No matching launch in the next 10 minutes.

## @toly 2026-11-24 20:06:52 UTC (post 2125320263655125146)
> Can’t prove it’s a super linear gap 🫳🎤

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 23 s | SLG | super linear gap | linear, super | price not recorded |  |  |  |  |
| 159 s | HOLD | Super Hold Labs | super | -89% | -89% | -100% | -100% | +78% (11 s) |

## @toly 2026-11-24 20:14:40 UTC (post 2125322230011982076)
> This makes no sense NYT spy leaks are speculation. No actual doj indictment, let alone presumption of innocence. Nvidia is important to gdp 

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-24 20:18:50 UTC (post 2125323275823915420)
> Pushing SPX6900 is already a glimpse of what a "Post-work society" looks like People banding into (tokenized) communities and evangelizing t

No matching launch in the next 10 minutes.

## @toly 2026-11-24 20:47:20 UTC (post 2125330450990383494)
> Is there a perpetual market on embarrassment? https://t.co/wWicxv2fnY

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 62 s | embarrassment | embarrassment coin | embarrassment | +36% | +46% | +46% | +46% | +68% (69 s) |

## @cz_binance 2026-11-24 21:17:25 UTC (post 2125338022094983414)
> My talk might be boring, but the venue is excellent. See you at the Louvre Abu Dhabi · December 3 and 4, 2026. https://t.co/fGI262dsc0

No matching launch in the next 10 minutes.

## @saylor 2026-11-24 21:31:49 UTC (post 2125341642756354145)
> Stretch ($STRC) led this fixed-income comparison on risk-adjusted returns over the past year. Its Sharpe ratio was +0.57, while all seven ET

No matching launch in the next 10 minutes.

## @toly 2026-11-24 22:07:40 UTC (post 2125350667737071814)
> Everyone fawning over neon 👇👇👇 https://t.co/6kPn9uuSTM

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-24 23:00:26 UTC (post 2125363942977597554)
> Starlink https://t.co/wMW5Hy970K

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 00:11:58 UTC (post 2125381945672761599)
> The news is accurate https://t.co/FLI7HDhXCf

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 00:18:35 UTC (post 2125383610266157090)
> Don’t mess with 𝕏 https://t.co/FNYSyWB7iv

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 00:19:34 UTC (post 2125383859592479201)
> Starlink is now approved in 30 of 54 countries in Africa! https://t.co/nTJTFLUD53

No matching launch in the next 10 minutes.

## @saylor 2026-11-25 00:46:16 UTC (post 2125390580305846369)
> Stretch ($STRC) led the asset benchmarks shown on risk-adjusted returns over the past year. Its Sharpe ratio was +0.57, ahead of the S&amp;P

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 02:08:07 UTC (post 2125411174993010839)
> Interesting https://t.co/XRd4shsO4N

No matching launch in the next 10 minutes.

## @toly 2026-11-25 03:28:05 UTC (post 2125431300303818849)
> 👑👑👑 https://t.co/MmHyE7QDyB

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-25 03:53:01 UTC (post 2125437574965539054)
> been on the phone w/ legal, devs &amp; coordinating with law enforcement all day attempted to get funds frozen while still in usdc but neede

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-25 04:17:50 UTC (post 2125443821437882440)
> next year is gonna be weird man https://t.co/czphv4WrQq

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 05:31:21 UTC (post 2125462322483503370)
> True https://t.co/yXQvmVvHhe

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 05:37:26 UTC (post 2125463852146114994)
> Impressive work by Google https://t.co/lMbNUq9Zd4

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-25 08:41:34 UTC (post 2125510194071543872)
> 📢 MiniMax H3 Image Series is Now Live on https://t.co/Id9VsXTy4C Chat https://t.co/aEzMirdsAh

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-25 10:36:23 UTC (post 2125539088250163564)
> 火币HTX美股版图版图越来越完整了！ https://t.co/Jfvx7H5p7f

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-25 11:31:49 UTC (post 2125553038639108228)
> Crypto massively rewards only 1 type of person. (a) An Extremely Patient Holder (b) with the Right Asset Selection You goal is to accomplish

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-25 12:31:02 UTC (post 2125567940821156177)
> 挺写实的 https://t.co/SV4fSjK9yP

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-25 12:33:02 UTC (post 2125568442250203359)
> 我的豆包已经快一年没有打开了

No matching launch in the next 10 minutes.

## @saylor 2026-11-25 12:57:21 UTC (post 2125574561735520444)
> Stretch ($STRC) returned 13% over the past year, leading all six benchmarks shown. The S&amp;P 500 ETF gained 9%, while Bitcoin fell 32%. ht

No matching launch in the next 10 minutes.

## @saylor 2026-11-25 14:53:08 UTC (post 2125603699204497670)
> Stretch ($STRC) returned 13.24% over the past year, beating all seven fixed-income ETFs in this comparison. The closest was Treasury bills a

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-25 15:59:20 UTC (post 2125620359101591990)
> Which human is 135 IQ and which human is 115 IQ will not matter soon when all AI agents are 200+ IQ. Which ironically means that the “High I

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-25 18:26:14 UTC (post 2125657329597301130)
> Every Finance, DeFi, CeFi, CeDeFi, CEX, DEX, Wallet and Social app is converging to the same exact design: "A Social Trading Platform with P

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SI | social, trading | +0%, no liq @1.2m | +0%, no liq @5.3m | +0%, no liq @15.5m | +0%, no liq @60.5m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 308 s | SI | Social Trading | social, trading | price not recorded |  |  |  |  |

## @elonmusk 2026-11-25 19:07:42 UTC (post 2125667762324541673)
> SpaceX Colossus 3 will greatly benefit the Arizona community https://t.co/l6KW6RkleF

No matching launch in the next 10 minutes.

## @MrBeast 2026-11-25 19:10:55 UTC (post 2125668575075811551)
> If you want a look behind the curtain on how a MrBeast video is made, watch this https://t.co/CYcaRUPasX

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 19:12:53 UTC (post 2125669066388209784)
> Interesting https://t.co/vywPrUlXEc

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-25 19:17:24 UTC (post 2125670205456257409)
> Thanks Ron ❤️ My greatest privilege is being able to work with the incredibly talented people of SpaceX, Tesla, Neuralink and Boring Company

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-25 21:12:04 UTC (post 2125699060392919192)
> One day you will wake up and see SPX6900 all over the news, valued at several hundred billion dollars You will think that you are “late” Onl

No matching launch in the next 10 minutes.

## @toly 2026-11-25 22:19:35 UTC (post 2125716053582078123)
> Rust walked so lean could run

No matching launch in the next 10 minutes.

## @a1lon9 2026-11-25 22:30:46 UTC (post 2125718869058650591)
> https://t.co/oAQHWDkJWU

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-25 22:32:38 UTC (post 2125719336228937841)
> On December 4th, we’re rolling out a block0 fee on all Pumpfun launches. The first seconds after a coin launches decide whether it gets a fa

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-25 22:32:39 UTC (post 2125719341643776031)
> How the block0 fee works: - Any buys or sells that occur in the same block as the coin creation transaction pays a flat % fee - Creators who

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-25 22:32:40 UTC (post 2125719345636733423)
> Learn more: https://t.co/X4QZ2e5Lmz

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-25 22:32:41 UTC (post 2125719350179225821)
> Follow our developer updates: https://t.co/gj6tl7uqbU

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-25 22:32:45 UTC (post 2125719366297854231)
> https://t.co/sR4r3cVbgy

No matching launch in the next 10 minutes.

## @toly 2026-11-25 22:55:12 UTC (post 2125725015098437732)
> 👑👑👑 https://t.co/vKNCS4Nxwz

No matching launch in the next 10 minutes.

## @toly 2026-11-25 23:25:08 UTC (post 2125732548814987476)
> 👑👑👑 https://t.co/PvfaaxcRfO

No matching launch in the next 10 minutes.

## @toly 2026-11-25 23:44:15 UTC (post 2125737358578618812)
> 👑👑👑 https://t.co/qJWPGgOvyb

No matching launch in the next 10 minutes.

## @toly 2026-11-25 23:56:27 UTC (post 2125740430545617199)
> BREAKING: BUG BOUNTY 69 rapidly strengthening pre singularity dollars are up for grabs to anyone that can exploit all the bugs lean-svm has 

No matching launch in the next 10 minutes.

## @toly 2026-11-26 00:47:06 UTC (post 2125753178054598974)
> svm-lean reduced the percolator ix CUs by 10x compared to the vibe coded rust version 🤯🤯🤯

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-26 02:17:33 UTC (post 2125775937405137135)
> If you use 1Password, recommend you to change ALL your passwords. It's a pain in the neck, but necessary. https://t.co/p5XpheMwVv

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-26 03:43:05 UTC (post 2125797463047258119)
> Every child in America will receive two SpaceX shares, one from the company and one from me personally

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| ameri | america | +0%, no liq @1.9m | +420%, no liq @6.0m | +34%, no liq @15.0m | +34%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 525 s | ameri | america russiar | america | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-26 04:12:02 UTC (post 2125804747852857401)
> TRON’s everyday use is a foundation institutions can build on. https://t.co/uYIlfFPfZy

No matching launch in the next 10 minutes.

## @VitalikButerin 2026-11-26 05:36:49 UTC (post 2125826087129358766)
> A shallow dive into open-source chip design: https://t.co/wHWMD0UwIy

No matching launch in the next 10 minutes.

## @VitalikButerin 2026-11-26 05:37:02 UTC (post 2125826142083158334)
> leanSeal ( https://t.co/I85xkixMHC ) ASIC in 240 lines of Verilog: https://t.co/lzCIylzOnR

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-26 06:01:08 UTC (post 2125832205301878841)
> The share from SpaceX will be transferred next month. The share directly from me will be transferred when my lockup expires in June next yea

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SPACEX | spacex | +0%, no liq @1.3m | -13%, no liq @5.4m | -13%, no liq @15.6m | -13%, no liq @60.7m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 514 s | SPACEX | SpaceX Coin | spacex | price not recorded |  |  |  |  |

## @VitalikButerin 2026-11-26 06:59:30 UTC (post 2125846895822328103)
> Cleverness is knowing that the elevator close button (at least in the US) doesn't actually make the door close any faster. Wisdom is ignorin

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| WI | wisdom | missed | missed | missed | missed | – | no |
| WI | wisdom | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 25 s | WI | wisdom inu | wisdom | price not recorded |  |  |  |  |
| 41 s | WI | wisdom inu | wisdom | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-26 07:00:02 UTC (post 2125847026265149474)
> Sunday on the Main Stage. See you in Bangkok. 🇹🇭 https://t.co/x5xI3Yo3xV

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-26 07:44:42 UTC (post 2125858270296285463)
> Hard to believe this finally happened https://t.co/427CZqEEZY

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-26 07:51:12 UTC (post 2125859903256326238)
> For most Cryptoassets, 100 people join during a bull market, and 97 leave during a bear market. For *special* Cryptoassets, 100 people join 

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| att | attention | +0%, no liq @2.0m | -18%, no liq @5.1m | -18%, no liq @15.6m | -18%, no liq @60.9m | – | no |
| ANSEM69 | bull | +0%, no liq @1.9m | +0%, no liq @5.2m | +26%, no liq @15.5m | -1%, no liq @60.9m | – | no |
| ANSEM15 | bull | +0%, no liq @1.9m | -1%, no liq @5.2m | -1%, no liq @15.5m | -13%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 195 s | att | attention | attention | -61% | -100% | -100% | -100% | +42% (1 s) |
| 506 s | ANSEM69 | The Black Bull 69 | bull | price not recorded |  |  |  |  |
| 509 s | ANSEM15 | The Black Bull 1.5 | bull | +0% | +0% | +0% | -13% | +49% (1579 s) |

## @elonmusk 2026-11-26 08:21:54 UTC (post 2125867631546712066)
> Teslas have superhuman vision https://t.co/6UigftjZTu

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 100 s | SI | Superhuman Inu | superhuman | price not recorded |  |  |  |  |
| 232 s | SC | super vision | vision | price not recorded |  |  |  |  |

## @elonmusk 2026-11-26 08:59:15 UTC (post 2125877031816630636)
> Boring Co has built a lot of tunnels under Vegas https://t.co/X8LkpfibIb

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-26 10:21:14 UTC (post 2125897661983375480)
> Congratulations to Bennett Chow, Yuan Liao, Ziyang Qin, and Ayush Khaitan on the first MathDB award. A Lean formalization of the Poincaré co

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-26 11:07:46 UTC (post 2125909371401961865)
> Flushes are not just needed, they are desirable. The more unbelievers we leave behind here, the more relentless the Parabolic Ascent later.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| Parabolic | ascent, parabolic | +0%, no liq @1.6m | -0%, no liq @5.8m | -0%, no liq @15.0m | -0%, no liq @60.4m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 64 s | Parabolic | Parabolic ascent | ascent, parabolic | +0% | -29% | -29% | -29% | +1% (0 s) |

## @justinsuntron 2026-11-26 11:30:01 UTC (post 2125914970835788118)
> Good to see @allscaleio adding support for USDT on TRON. 🔻 https://t.co/oeGjEoxfmU

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-26 11:49:00 UTC (post 2125919748391334067)
> 看到小红书上有人质疑我的财富量级。就这么说吧：昨天我写代码做任务，敢让Claude Fable 5.2 Ultracode 跑了 11 个小时。 开的是 API，按量计费。

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-26 12:29:51 UTC (post 2125930030572437822)
> Keep building! https://t.co/HyXXmgwOuv

No matching launch in the next 10 minutes.

## @saylor 2026-11-26 13:15:03 UTC (post 2125941406128607460)
> Relative to market cap, $MSTR had 4.4× the options open interest of Tesla, the leader among the Magnificent Seven. Open contracts on $MSTR r

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-26 13:50:01 UTC (post 2125950204452950505)
> Those who accept that transforming their life takes years, have transformed their life the moment they accepted this. In the meantime, every

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 178 s | trench | trench life | life | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-26 16:05:04 UTC (post 2125984189044740452)
> The coming Bull Run will be Glorious. But now is when that Glory is earned.

No matching launch in the next 10 minutes.

## @saylor 2026-11-26 17:43:30 UTC (post 2126008963850518995)
> Fix the Money, Fix the World https://t.co/oDMci9tM6D

No matching launch in the next 10 minutes.

## @saylor 2026-11-26 17:44:38 UTC (post 2126009248190800326)
> https://t.co/3ODgwVqibK

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-26 19:14:42 UTC (post 2126031911713964534)
> The difference between spx6900 and everything else, is that what we are doing, is going to set us up for life.

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-26 20:00:12 UTC (post 2126043363724161265)
> Over 60,000 callers have been rewarded for calling coins on the Pumpfun app 💰 Callers have earned a total of $37,000,000 since August! https

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| CALLERS | callers | +0%, no liq @2.2m | -13%, no liq @5.4m | -13%, no liq @16.0m | -13%, no liq @60.2m | – | no |
| CALLERS | callers | +0%, no liq @2.2m | -10%, no liq @5.3m | -10%, no liq @15.9m | -10%, no liq @60.2m | – | no |
| CALLING | calling | +0%, no liq @2.2m | -5%, no liq @5.3m | -5%, no liq @15.9m | -5%, no liq @60.2m | – | no |
| CALLERS | callers | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 14 s | CALLERS | Callers | callers | price not recorded |  |  |  |  |
| 16 s | CALLING | Just Start Calling | calling | price not recorded |  |  |  |  |
| 16 s | CALLERS | The Callers | callers | price not recorded |  |  |  |  |
| 74 s | CALLERS | The Callers | callers | price not recorded |  |  |  |  |

## @elonmusk 2026-11-26 20:07:10 UTC (post 2126045116624216127)
> ❤️❤️ Happy Thanksgiving! ❤️❤️

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 238 s | POTATO | Thanksgiving Potato | thanksgiving | price not recorded |  |  |  |  |

## @a1lon9 2026-11-26 20:28:01 UTC (post 2126050363178426504)
> We’re hiring a Talent Manager (Creators &amp; Content) at Baton Corporation, the development company behind Pumpfun. We’re working with some

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| MCAT | manager, talent | +0%, no liq @1.4m | +1%, no liq @5.6m | -0%, no liq @15.0m | -0%, no liq @60.5m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 362 s | MCAT | Talent Manager Cat | manager, talent | price not recorded |  |  |  |  |

## @a1lon9 2026-11-26 20:28:01 UTC (post 2126050365481107931)
> Apply here: https://t.co/WDqsvT6hRZ

No matching launch in the next 10 minutes.

## @toly 2026-11-26 20:45:33 UTC (post 2126054777914270051)
> 👑👑👑 https://t.co/U5w6d7CEsA

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-26 21:23:31 UTC (post 2126064330022265197)
> Super appreciate your support. Tesla wouldn’t be where it is without our awesome customers. https://t.co/XWgsthy0wO

No matching launch in the next 10 minutes.

## @toly 2026-11-26 21:44:51 UTC (post 2126069699360543202)
> BREAKING: BUG BOUNTY (round 3: i know you are hiding from your family anyways) My dream is a money lego for perps that is just one tiny risk

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 73 s | MONEYLEGOS | Money Legos | money | -0% | -0% | -0% | -0% | +0% (0 s) |
| 303 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 308 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 328 s | FAMILY | genny??? | family | price not recorded |  |  |  |  |
| 335 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 345 s | FAMILY | genny??? | family | price not recorded |  |  |  |  |
| 348 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 355 s | FAMILY | genny??? | family | price not recorded |  |  |  |  |
| 409 s | FAMILY | genny??? | family | price not recorded |  |  |  |  |
| 414 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 416 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 420 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 425 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 426 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 432 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 441 s | FAMILY | READ? | family | price not recorded |  |  |  |  |
| 442 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |
| 445 s | FAMILY | Family Flow | family | price not recorded |  |  |  |  |

## @toly 2026-11-26 21:46:20 UTC (post 2126070070950686785)
> https://t.co/dQa9JbDUUM

No matching launch in the next 10 minutes.

## @toly 2026-11-26 22:33:06 UTC (post 2126081840775827589)
> 👑👑👑 https://t.co/STIjh86pKW

No matching launch in the next 10 minutes.

## @toly 2026-11-26 22:42:49 UTC (post 2126084285967016079)
> 👑👑👑 https://t.co/aSGWiP1CC8

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-27 00:26:21 UTC (post 2126110344120762593)
> Vital that children have a stake in the future https://t.co/KtSGi3dSF7

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 274 s | FUTURE | the future | future | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-27 01:32:09 UTC (post 2126126899516854617)
> go birds

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| $BIRDS | birds | +0%, no liq @1.1m | -1%, no liq @5.4m | -1%, no liq @16.0m | -1%, no liq @61.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 123 s | $BIRDS | BIRD | birds | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-27 02:32:15 UTC (post 2126142027897409678)
> 来试试 $USDD 的原生抵押借贷吧！ETH WBTC wSTETH 全支持！ https://t.co/vWJo6D2QLj

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-27 02:32:26 UTC (post 2126142072491245817)
> Happy Thanksgiving! 🦃

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-27 02:32:41 UTC (post 2126142133526790186)
> USDD 启动！ https://t.co/Wek6L61ZO3

No matching launch in the next 10 minutes.

## @toly 2026-11-27 02:38:58 UTC (post 2126143715924435374)
> Only Uncs https://t.co/CZkFmCUNI8

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| UNCS | uncs | +0%, no liq @1.9m | -2%, no liq @5.1m | -14%, no liq @15.9m | -14%, no liq @60.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 47 s | UNCS | uncs | uncs | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-27 05:29:30 UTC (post 2126186631023763610)
> few. https://t.co/Z1nPxKqVwM

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-27 05:54:00 UTC (post 2126192796927144275)
> .@BAI_AGI in Bangkok. 🇹🇭 https://t.co/qiMGyhizXq

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-27 06:01:51 UTC (post 2126194774931857559)
> Who's in Bangkok?

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| BANGKOK | bangkok | +0%, no liq @1.1m | -1%, no liq @5.4m | -1%, no liq @15.1m | -1%, no liq @60.5m | – | no |
| Bangkok | bangkok | +0%, no liq @1.4m | +1%, no liq @5.8m | +1%, no liq @15.5m | +2%, no liq @60.9m | – | no |
| BANGKOK | bangkok | +0%, no liq @1.5m | +0%, no liq @5.8m | +0%, no liq @15.5m | +0%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 172 s | BANGKOK | BANGKOK | bangkok | price not recorded |  |  |  |  |
| 216 s | Bangkok | who’s bangkok | bangkok | price not recorded |  |  |  |  |
| 278 s | BANGKOK | WHO IS BANGKOK | bangkok | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-27 06:42:00 UTC (post 2126204876543627711)
> Credit by role: the solver, the formalizer, and the exposition. #JustinSunPrize https://t.co/rrZWUYX3x8

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-27 07:52:41 UTC (post 2126222666994737622)
> True https://t.co/onabG4ka4u

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 108 s | TRUE | True | true | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-27 08:32:07 UTC (post 2126232590533132359)
> Every time Crypto (and TradFi) prices go down, I get more EXCITED, for the following reasons: (1) We necessarily get rid of the non-believer

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-27 10:47:27 UTC (post 2126266645476000044)
> First of two AMAs today. Had to rush to the next event, so didn't stay for photos. Will do book signing and some selfies tmr after the fires

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-27 10:58:34 UTC (post 2126269445467422728)
> 2nd AMA today, at the beautiful Stonehill golf club. Very influential crowd. Great conversations. 🙏 https://t.co/yh21husud4

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| GPRP | club | +0%, no liq @1.1m | +0%, no liq @5.4m | +0%, no liq @15.1m | +1%, no liq @60.1m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 474 s | GPRP | Grandpa RugPull Club | club | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-27 11:20:07 UTC (post 2126274868220248472)
> Crypto is a blessing for those who think long-term and a curse for those who think short-term

No matching launch in the next 10 minutes.

## @VitalikButerin 2026-11-27 12:23:46 UTC (post 2126290884786528279)
> TIL: rhinodinos https://t.co/mYud8P7EWa

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| rhinodinos | rhinodinos | missed | missed | missed | missed | – | no |
| rhinodinos | rhinodinos | missed | missed | missed | missed | – | no |
| RHINODINOS | rhinodinos | +0%, no liq @1.8m | +0%, no liq @5.0m | +0%, no liq @15.7m | +0%, no liq @60.8m | – | no |
| RHINODINOS | rhinodinos | missed | missed | missed | missed | – | no |
| RHINODINOS | rhinodinos | missed | missed | missed | missed | – | no |
| RHINODINOS | rhinodinos | missed | missed | missed | missed | – | no |
| RHINODINOS | rhinodinos | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 30 s | rhinodinos | rhinodinos | rhinodinos | price not recorded |  |  |  |  |
| 44 s | rhinodinos | rhinodinos | rhinodinos | price not recorded |  |  |  |  |
| 209 s | RHINODINOS | rhinodinos | rhinodinos | price not recorded |  |  |  |  |
| 219 s | RHINODINOS | Rhinodinoscoin | rhinodinos | price not recorded |  |  |  |  |
| 224 s | RHINODINOS | Rhinodinoscoin | rhinodinos | price not recorded |  |  |  |  |
| 337 s | RHINODINOS | Paraceratherium | rhinodinos | price not recorded |  |  |  |  |
| 352 s | RHINODINOS | Paraceratherium | rhinodinos | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-27 13:34:34 UTC (post 2126308705243107583)
> People think that peak Bull Market is when you have to “lock in” Wrong. It’s right now.

No matching launch in the next 10 minutes.

## @saylor 2026-11-27 14:43:25 UTC (post 2126326029728063994)
> On Nov. 25, the 13-week U.S. Treasury bill (IRX), a three-month benchmark for dollar credit, was quoted at a 4.16% discount rate. Stretch ($

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-27 14:47:53 UTC (post 2126327154397118710)
> Thank you @BitkubOfficial for a great evening in Bangkok and for having me speak tonight. https://t.co/0L1yRICm6h

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-27 15:40:59 UTC (post 2126340518103961999)
> Bangkok, look up. 🔻 https://t.co/8FosfWBzee

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-27 16:53:02 UTC (post 2126358649492910244)
> What if AGI comes, but instead of life getting better for everyone, it gets +200% better for the top 5% and -60% worse for the bottom 95%?

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| AGI | agi | +0%, no liq @1.5m | -3%, no liq @5.8m | -4%, no liq @15.7m | -4%, no liq @60.9m | – | no |
| GETPAID | getting | +0%, no liq @1.5m | +0%, no liq @5.8m | +0%, no liq @15.7m | +0%, no liq @60.9m | – | no |
| AGI | agi | +0%, no liq @1.5m | +0%, no liq @5.8m | +0%, no liq @15.7m | +0%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 60 s | AGI | a good investment | agi | price not recorded |  |  |  |  |
| 62 s | AGI | a good investment | agi | price not recorded |  |  |  |  |
| 62 s | GETPAID | You guys are getting paid? | getting | -45% | -45% | -45% | -45% | +189% (0 s) |

## @MrBeast 2026-11-27 19:18:01 UTC (post 2126395136192160056)
> I JUST BOUGHT 100 CARS and this Sunday I’m giving them all away FOR FREE on a Whatnot Livestream! Download Whatnot and tune in Sunday at 2pm

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-27 20:18:48 UTC (post 2126410433011868133)
> Strongest Memes ever invented: Dollar Bitcoin SPX6900

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| BTC | bitcoin | +0%, no liq @1.5m | +0%, no liq @5.8m | +0%, no liq @15.5m | +0%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 319 s | BTC | Bitcoin | bitcoin | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-27 21:10:19 UTC (post 2126423398540812610)
> More than 1 in 3 callers who made $1,000+ this week had under 1k trader followers. No matter the market, who you are or what you trade, Call

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| E | everyone | +0%, no liq @1.0m | -66%, no liq @5.3m | -66%, no liq @16.0m | -66%, no liq @60.1m | – | no |
| CI | callout | +0%, no liq @1.6m | +3%, no liq @5.8m | -5%, no liq @15.4m | -5%, no liq @60.6m | – | no |
| CI | callout | +0%, no liq @1.2m | -17%, no liq @5.4m | -17%, no liq @15.1m | -17%, no liq @60.2m | – | no |
| CI | callout | +0%, no liq @1.6m | +0%, no liq @5.8m | +0%, no liq @15.5m | +0%, no liq @60.6m | – | no |
| CI | callout | +0%, no liq @1.8m | +0%, no liq @5.0m | +0%, no liq @15.7m | +0%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 235 s | E | Everyone Coin | everyone | +11% | +11% | +11% | +11% | +15% (25 s) |
| 269 s | CI | callout inu | callout | price not recorded |  |  |  |  |
| 292 s | CI | callout inu | callout | price not recorded |  |  |  |  |
| 331 s | CI | callout inu | callout | +0% | +0% | +0% | +0% | +183% (1 s) |
| 382 s | CI | callout inu | callout | +0% | +0% | +0% | +0% | +0% (1 s) |

## @toly 2026-11-27 21:22:41 UTC (post 2126426507686076539)
> 🤯🤯🤯 https://t.co/OiAwiV7BMj

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-27 21:29:54 UTC (post 2126428324012446090)
> The goal with Grok Bots is to enable you to build a whole company! https://t.co/rLPoReaR6R

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 550 s | Pumpfamli | Whole Coin | whole | price not recorded |  |  |  |  |

## @elonmusk 2026-11-27 21:34:02 UTC (post 2126429365504229400)
> Worth trying https://t.co/oqe53VZr0X

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-27 22:08:23 UTC (post 2126438008748384711)
> Give Grok Bot your hardest problems https://t.co/jCbD27mE3F

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 94 s | Grok | The Everything Bot | grok | price not recorded |  |  |  |  |
| 181 s | Grok | The Everything Bot | grok | -71% | -71% | -71% | -71% | +25% (8 s) |
| 275 s | Grok | The Everything Bot | grok | -72% | -72% | -72% | -72% | +264% (53 s) |
| 388 s | Grok | The Everything Bot | grok | price not recorded |  |  |  |  |
| 418 s | Grok | The Everything Bot | grok | +0% | -69% | -69% | -69% | +0% (3 s) |
| 440 s | Grok | The Everything Bot | grok | -1% | -1% | -1% | -1% | +224% (2 s) |
| 458 s | Grok | The Everything Bot | grok | +0% | +0% | +0% | +0% | +212% (2 s) |
| 489 s | Grok | The Everything Bot | grok | -0% | -0% | -0% | -0% | +238% (3 s) |
| 526 s | Grok | The Everything Bot | grok | +0% | -66% | -66% | -66% | +0% (0 s) |

## @elonmusk 2026-11-27 22:08:57 UTC (post 2126438150314631286)
> This is the way https://t.co/VlkdujMi4d

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-27 22:10:11 UTC (post 2126438463520350588)
> Give each Bot a specific job, just like people in a company https://t.co/BKIliX3HzA

No matching launch in the next 10 minutes.

## @toly 2026-11-27 22:43:44 UTC (post 2126446905991561444)
> Boil em, mash em https://t.co/AI0k5oUTkB

No matching launch in the next 10 minutes.

## @toly 2026-11-27 23:50:13 UTC (post 2126463636046741900)
> Upgrade pls!!! https://t.co/QaC2yPf0pQ

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| UPGRADE | upgrade | missed | missed | +0%, no liq @15.1m | +0%, no liq @60.9m | – | no |
| UPGRADE | upgrade | missed | missed | +0%, no liq @15.7m | +0%, no liq @60.4m | – | no |
| UPGRADE | upgrade | missed | missed | +0%, no liq @15.3m | +0%, no liq @60.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 18 s | UPGRADE | Upgrade Now | upgrade | price not recorded |  |  |  |  |
| 45 s | UPGRADE | Upgrade Now | upgrade | -68% | -70% | -70% | -70% | +59% (20 s) |
| 71 s | UPGRADE | Upgrade Now | upgrade | -66% | -66% | -66% | -66% | +138% (24 s) |

## @toly 2026-11-27 23:51:31 UTC (post 2126463962661470442)
> It’s Friday 😭😭😭

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| FRIDAY | friday | missed | missed | +0%, no liq @16.0m | +0%, no liq @60.7m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 14 s | FRIDAY | It’s Friday | friday | price not recorded |  |  |  |  |

## @toly 2026-11-27 23:57:58 UTC (post 2126465585957806316)
> 👑👑👑 https://t.co/UstnN7KaGg

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-28 00:54:09 UTC (post 2126479727066272164)
> Extremely troubling https://t.co/36CuHTvPxY

No matching launch in the next 10 minutes.

## @toly 2026-11-28 01:18:35 UTC (post 2126485875534225887)
> 👑👑👑 https://t.co/9yBBEKIQVz

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-28 01:19:05 UTC (post 2126486002919494134)
> Great to visit the @BitkubOfficial team in Bangkok. Thanks for the welcome. 🇹🇭 https://t.co/5N3DqhfVH1

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-28 06:20:45 UTC (post 2126561915925414299)
> Joining @ellazhang516 for a fireside chat at EASY Residency Season 5 Demo Day today, 2:45 PM Bangkok time. Watch live 👇 https://t.co/VOfe0xB

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-28 06:43:47 UTC (post 2126567714625880064)
> Users on affected iOS versions (18.4–18.7) will see this warning pop up across most of our ecosystem apps and websites where OS detection is

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-28 06:53:13 UTC (post 2126570086857388528)
> 来试试 USDD 原生以太坊支持吧！ https://t.co/0WxdpHEoDM

No matching launch in the next 10 minutes.

