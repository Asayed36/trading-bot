# X posts and the pump.fun launches after them

Measurement only (screener/xposts_report.py), written 2026-11-26 07:04 UTC, the last 7 days. For each post, the new launches in the 10 minutes after it whose name or symbol matches a word of the post. Price moves are from the first recorded price (5 s after the launch) and exist only for the launches the launch recorder followed (qualified launches and a 2% sample); a match is not a cause.

284 post(s), 142 matching launch(es).

## Ticker mentions

Recording only (screener/xmentions.py), the last 7 days. Cashtags, Solana and EVM addresses in the saved posts (at most 5 a post), each looked up once on DexScreener. Changes are from the price at the first check (not the post's own time); BTC is over the same real times, from the once-a-minute price log. "large": BTC, ETH, SOL, BNB, XRP, DOGE or above $5 billion. A handful of mentions says nothing yet; a mention is not a cause.

13 mention(s) in 11 post(s): 13 identified.

| Account | Coins | Mentions | 5m coin avg / median (n) | 5m BTC avg / median | 15m coin avg / median (n) | 15m BTC avg / median | 60m coin avg / median (n) | 60m BTC avg / median |
|---|---|---|---|---|---|---|---|---|
| @blknoiz06 | small | 1 | –, 1 missed | – | –, 1 missed | – | –, 1 missed | – |
| @cz_binance | small | 1 | +0.00% / +0.00% (1) | +0.07% / +0.07% | +0.00% / +0.00% (1) | +0.13% / +0.13% | +0.00% / +0.00% (1) | +0.81% / +0.81% |
| @saylor | large | 2 | +0.00% / +0.00% (2) | +0.14% / +0.14% | +0.00% / +0.00% (2) | +0.43% / +0.43% | +0.00% / +0.00% (2) | +1.51% / +1.51% |
| @saylor | small | 9 | +0.01% / +0.00% (9) | +0.06% / +0.08% | +0.01% / +0.00% (9) | +0.08% / -0.03% | +0.85% / +0.00% (9) | +0.97% / +0.11% |

Latest mentions (newest first; candidates = different tokens with that symbol in DexScreener's search answer, so more than 1 means the ticker is ambiguous):

| Posted (UTC) | Account | Mention | Coin | Candidates | Large | First check after | 1 h change at first check | 5m | 15m | 60m | 24h |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-25 14:53 | @saylor | $STRC | STRC (base) | 3 | no | 1.1 min | – | +0.0% | +0.0% | +0.0% | – |
| 2026-11-25 12:57 | @saylor | $STRC | STRC (base) | 3 | no | 1.0 min | – | +0.0% | +0.0% | +0.0% | – |
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
| @a1lon9 | 5 | 0 | – | 1: 1 X error or pause |
| @blknoiz06 | 43 | 31 | 17 other, 14 not recorded | 2629: 2629 per-account limit |
| @cz_binance | 20 | 1 | 1 not recorded | 80: 80 per-account limit |
| @elonmusk | 47 | 30 | 17 other, 13 not recorded | 2489: 2489 per-account limit |
| @justinsuntron | 44 | 22 | 8 other, 14 not recorded | 1791: 1791 per-account limit |
| @mrbeast | 5 | 0 | – | – |
| @muststopmurad | 34 | 1 | 1 not recorded | 27: 26 per-account limit, 1 X error or pause |
| @pumpfun | 33 | 9 | 3 other, 6 not recorded | 379: 378 per-account limit, 1 X error or pause |
| @realdonaldtrump | 0 | 0 | – | 1: 1 X error or pause |
| @saylor | 21 | 1 | 1 other | 207: 207 per-account limit |
| @toly | 49 | 40 | 25 other, 15 not recorded | 3543: 3543 per-account limit |
| @vitalikbuterin | 3 | 0 | – | – |

## Posts and the launches after them

## @toly 2026-11-19 00:54:01 UTC (post 2123218201941250180)
> 👑👑👑 https://t.co/mUY4n9huOC

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-19 01:03:30 UTC (post 2123220589657944265)
> Yes https://t.co/eDRBZQEVes

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 03:52:44 UTC (post 2123263179199537339)
> Japan's Personal Information Protection Commission issued a notice urging rental car operators to promptly delete images of driver's license

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 04:51:00 UTC (post 2123277839881338989)
> $94.21B in USDT on TRON. 🔻 https://t.co/EE58q9M2bg

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 05:49:30 UTC (post 2123292561154646062)
> JST确实硬，小TRX名不虚传 https://t.co/e3toeK75fX

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 05:49:55 UTC (post 2123292667471970764)
> 币圈长江电力 https://t.co/0i1QLAHsVP

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 05:51:25 UTC (post 2123293044145545277)
> 来火币都市感受一下！ https://t.co/zCAxxSPJg5

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-19 08:31:32 UTC (post 2123333341932052749)
> Starlink started with a speech in Seattle https://t.co/y8QLexDwnu

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 55 s | OSCCYL | one speech can change your life | speech | price not recorded |  |  |  |  |
| 64 s | OSCCYL | one speech can change your life | speech | price not recorded |  |  |  |  |
| 114 s | SPEECH | one speech can change your life | speech | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-19 08:45:09 UTC (post 2123336765931139300)
> To find the coin that will be the Biggest Household Name when we are in the middle of a Raging Bull Market… Find a community that acts as if

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-19 08:48:41 UTC (post 2123337655731826810)
> Extend consciousness to the stars https://t.co/vRKCpiPqyV

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 152 s | CONSCIOUSN | the future of consciousness | consciousness | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-19 09:53:26 UTC (post 2123353948979691564)
> 24/7 payments is the right goal. Stablecoins on TRON never sleeps. 🔻 https://t.co/GWKy0JCCc8

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 10:14:57 UTC (post 2123359363901616560)
> TRON in Bangkok 🇹🇭 tron:native https://t.co/VTlcceFEEo

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-19 10:15:33 UTC (post 2123359517325062354)
> AI 是懂行的！ https://t.co/5lAgpryMTZ

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-19 11:48:18 UTC (post 2123382855762079794)
> Late 2018 and Late 2022 have proven to be some of the greatest entries in crypto history. The same will be said about Late 2026.

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-19 13:55:37 UTC (post 2123414899166757311)
> Every time you say SPX6900 will flip the stock market you increase the probability of it happening by another +0.00001%

No matching launch in the next 10 minutes.

## @saylor 2026-11-19 14:17:57 UTC (post 2123420518967591217)
> $STRC traded over $600M yesterday, the only one of 456 U.S.-listed income preferreds to do so this year. We intend to keep buying below $100

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-19 14:50:03 UTC (post 2123428598014967818)
> santa rally.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SANTA | rally, santa | +0%, no liq @2.5m | -13%, no liq @5.7m | -13%, no liq @15.3m | -15%, no liq @60.9m | – | no |
| SANTA | rally, santa | +0%, no liq @2.5m | +0%, no liq @5.6m | -12%, no liq @15.2m | -12%, no liq @60.8m | – | no |
| SANTA | rally, santa | +0%, no liq @1.9m | -0%, no liq @5.0m | -0%, no liq @15.8m | -0%, no liq @60.2m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 14 s | SANTA | Santa Rally | rally, santa | price not recorded |  |  |  |  |
| 16 s | SANTA | Santa Rally | rally, santa | price not recorded |  |  |  |  |
| 242 s | SANTA | Santa Rally | rally, santa | price not recorded |  |  |  |  |

## @cz_binance 2026-11-19 17:29:03 UTC (post 2123468610169675796)
> Cancelling Netflix 🤣 https://t.co/qL32ISZl9E

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 17:29:27 UTC (post 2123468710245519732)
> 😂 https://t.co/6cMBkz6Of8

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 17:32:28 UTC (post 2123469470027133011)
> Bloomberg's report on Netflix. https://t.co/t5fq6iK3FN https://t.co/e9wuLPZcPv

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| BLOOMBERG | bloomberg | +0%, no liq @1.7m | -1%, no liq @5.9m | -1%, no liq @15.4m | -1%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 300 s | BLOOMBERG | Bloomberg | bloomberg | price not recorded |  |  |  |  |

## @a1lon9 2026-11-19 17:43:09 UTC (post 2123472157720109194)
> I firmly believe the best callers of the next cycle will be the ones who call the most runners with the highest accuracy - so I want to be V

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| CALLERS | callers | +0%, no liq @2.0m | -14%, no liq @5.2m | -15%, no liq @15.8m | -16%, no liq @60.2m | – | no |
| BELIEVE | believe | +0%, no liq @1.8m | -18%, no liq @6.0m | -18%, no liq @15.5m | -18%, no liq @60.9m | – | no |
| BELIEVE | believe | missed | missed | missed | missed | – | no |
| Believe | believe | +0%, no liq @1.1m | -68%, no liq @5.3m | -68%, no liq @15.8m | -68%, no liq @60.2m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 80 s | CALLERS | The Callers | callers | price not recorded |  |  |  |  |
| 225 s | BELIEVE | Believe | believe | price not recorded |  |  |  |  |
| 288 s | BELIEVE | Believe | believe | price not recorded |  |  |  |  |
| 392 s | Believe | Believe | believe | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-19 17:46:44 UTC (post 2123473061991034902)
> AI Agents and Hyper-automation will cause a massive shift from Gambling to Believing. Short term Speculation -&gt; to Long-term HODL Value w

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| HODL | hardcore, hodl | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 31 s | HODL | Hardcore HODL | hardcore, hodl | price not recorded |  |  |  |  |

## @elonmusk 2026-11-19 17:56:17 UTC (post 2123475464043786417)
> You can create an entire company made of Grok Bots! https://t.co/qLl5REpV2h

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 17:59:30 UTC (post 2123476275071521147)
> Perps partial closes are now live on Pumpfun: take profit on part of a position and let the rest run Powered by Hyperliquid. https://t.co/xV

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| https | profit | +0%, no liq @1.6m | +0%, no liq @5.8m | +0%, no liq @15.3m | +0%, no liq @60.7m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 79 s | https | Had To Take Profit Sir | profit | +0% | -56% | -56% | -56% | +0% (1 s) |

## @Pumpfun 2026-11-19 17:59:32 UTC (post 2123476280083620238)
> Learn more about the $1,000,000 Perps Open, starting 20 November, 16:00 UTC: https://t.co/83sZn8H6IE

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 17:59:33 UTC (post 2123476284512854458)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 17:59:36 UTC (post 2123476296466629051)
> https://t.co/gTVMQk5ZUb

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 17:59:36 UTC (post 2123476300203807021)
> Also, quite a number of Japanese banks reported data leaks recently. Many other banks probably just not reporting/admitting/knowing. There w

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 18:05:31 UTC (post 2123477787709432072)
> Perps partial closes are live on Pumpfun: take profit on part of a position and let the rest run Powered by Hyperliquid https://t.co/z95gPUC

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 18:05:32 UTC (post 2123477792453263793)
> Learn more about the $1,000,000 Perps Open, starting 20 November, 16:00 UTC: https://t.co/83sZn8H6IE

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 18:05:33 UTC (post 2123477797461172656)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 18:05:36 UTC (post 2123477809658220729)
> https://t.co/BHzsPfz7om

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 18:10:24 UTC (post 2123479017785618463)
> Inflation will follow 👇. Not financial advice, but might be good to hold assets with limited supply. https://t.co/NTD6qo2mtd

No matching launch in the next 10 minutes.

## @MrBeast 2026-11-19 18:57:02 UTC (post 2123490752504434960)
> My first 100 hours in GTA 6 is now live on the gaming channel! We also are doing daily uploads now to celebrate GTA 6 Some of our best video

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| GTA | gta | +0%, no liq @1.5m | -8%, no liq @5.7m | -12%, no liq @15.3m | -12%, no liq @60.9m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 245 s | GTA | Gay Twink Autism | gta | -55% | -55% | -67% | -67% | +25% (2 s) |

## @MrBeast 2026-11-19 19:00:11 UTC (post 2123491544648880404)
> My first 100 hours in GTA 6 is now live on the gaming channel! Thank you Rockstar for trusting us with playing the game early, very grateful

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| GTA | gta | +0%, no liq @1.3m | +0%, no liq @5.5m | -2%, no liq @15.1m | -2%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 56 s | GTA | Gay Twink Autism | gta | -55% | -55% | -67% | -67% | +25% (2 s) |
| 449 s | GTA | Grand Token Avenue | gta | price not recorded |  |  |  |  |

## @Pumpfun 2026-11-19 20:39:38 UTC (post 2123516572497256912)
> Trading Anthropic tokenized stock on Solana or Base? Callout your trades via the Pumpfun app to be eligible for BOOSTED Callout Rewards! htt

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 268 s | Brian | CHECK PUMPFUN POST | pumpfun | price not recorded |  |  |  |  |
| 339 s | A\ | Anthropic \Nu | anthropic | price not recorded |  |  |  |  |
| 340 s | A\ | Anthropic \Nu | anthropic | price not recorded |  |  |  |  |
| 394 s | A\ | Anthropic \nu | anthropic | price not recorded |  |  |  |  |
| 467 s | GTA | Grand Theft Anthropic | anthropic | price not recorded |  |  |  |  |
| 517 s | A\ | Anthropic \nu | anthropic | price not recorded |  |  |  |  |
| 523 s | A\ | ANTHROPIC COIN | anthropic | price not recorded |  |  |  |  |
| 575 s | GTA | Grand Theft Anthropic | anthropic | price not recorded |  |  |  |  |
| 583 s | A\ | ANTHROPIC COIN | anthropic | price not recorded |  |  |  |  |
| 585 s | A\ | Official Anthropic Coin | anthropic | price not recorded |  |  |  |  |
| 598 s | A\ | Official Anthropic Coin | anthropic | price not recorded |  |  |  |  |

## @MustStopMurad 2026-11-19 20:57:52 UTC (post 2123521159119716587)
> 2000s and 2010s were marked by the Internet and Bitcoin 2020s and 2030s will be marked by AI and SPX6900

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-19 21:52:47 UTC (post 2123534980479590620)
> holy smokestacks https://t.co/oJzbIJMpGS

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-19 22:01:51 UTC (post 2123537260893319191)
> Plasma is live on the Pumpfun app! Callout tokens on Plasma to be eligible for Callout Rewards &amp; trade seamlessly with no bridging requi

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 143 s | Plasma | Plasma | plasma | price not recorded |  |  |  |  |
| 210 s | Plasma | Plasma Coin | plasma | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-19 22:08:22 UTC (post 2123538903244398812)
> ❄️❄️❄️ https://t.co/2aAm08EjkH https://t.co/gVg0whx9GV

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-19 22:10:17 UTC (post 2123539385690046902)
> bro smoked me but i didnt lie https://t.co/XEghNcFndN

No matching launch in the next 10 minutes.

## @toly 2026-11-19 22:24:40 UTC (post 2123543006569787506)
> 🫳🎤 https://t.co/n7Sz1eK8tR

No matching launch in the next 10 minutes.

## @toly 2026-11-19 22:36:38 UTC (post 2123546017308217664)
> London is an s-tier city, and I got to meet the man who had the 4th largest nuclear arsenal in his hands. https://t.co/GQoHDwSdsA

No matching launch in the next 10 minutes.

## @cz_binance 2026-11-19 22:53:37 UTC (post 2123550289957658970)
> Forbes: "Apparently, the most pressing unanswered question about the $8 billion FTX fraud is whether SBF ever really loved Caroline Ellison.

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 454 s | FNUT | Fraud Nut | fraud | price not recorded |  |  |  |  |

## @a1lon9 2026-11-19 23:11:03 UTC (post 2123554677924958318)
> We’re hiring two new roles for our marketing team at Baton Corporation, the development company behind Pumpfun: a Video Editor/Videographer 

No matching launch in the next 10 minutes.

## @a1lon9 2026-11-19 23:11:04 UTC (post 2123554681297437042)
> Apply for the Videographer/Editor Role: https://t.co/JfIwpI9aZV Apply for the Social Media Manager role: https://t.co/YBIXvtfUZt

No matching launch in the next 10 minutes.

## @toly 2026-11-19 23:37:52 UTC (post 2123561424387768521)
> 👑👑👑 https://t.co/unjACmeIoJ

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-19 23:39:08 UTC (post 2123561744119517315)
> 6 weeks ago all indices were at all time highs

No matching launch in the next 10 minutes.

## @toly 2026-11-19 23:43:52 UTC (post 2123562934207230001)
> 👑👑👑 https://t.co/TwRguhIWrB

No matching launch in the next 10 minutes.

## @toly 2026-11-19 23:47:57 UTC (post 2123563964068163853)
> I think the opposition to the Netflix slop has united more crypto factions than even gensler. https://t.co/Az8TU8TLxg

No matching launch in the next 10 minutes.

## @toly 2026-11-20 00:34:59 UTC (post 2123575798489825742)
> I think tradfi is not quoting nbbo if it’s not quoting solana https://t.co/e6hSokT2g4

No matching launch in the next 10 minutes.

## @saylor 2026-11-20 00:42:48 UTC (post 2123577768914923974)
> How do we decide when to buy Bitcoin and when to buy back $STRC? In Strategy’s Q3 2026 Investor Q&amp;A with @NatBrunell, @PhongLe and I ans

No matching launch in the next 10 minutes.

## @saylor 2026-11-20 00:42:49 UTC (post 2123577772601696480)
> You can also watch our full Q3 2026 Investor Q&amp;A on YouTube. https://t.co/P0Zs1V6wbv https://t.co/qbCk9j2iJ3

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 00:54:39 UTC (post 2123580750293512514)
> https://t.co/KwQdBJMiPv

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 02:29:44 UTC (post 2123604677149212884)
> w/ context of Qs breaking down, gold breaking down, dollar immense strength into likely more fed hikes &amp; nvda continued weakness seems u

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-20 07:35:32 UTC (post 2123681633589149750)
> USDT on TRON, now in @PulsarMoneyApp. 🔻 https://t.co/kIigXBYBuM

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 08:29:54 UTC (post 2123695317375992288)
> This is not AI 😂 https://t.co/7QlYzcVszJ

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 10:34:05 UTC (post 2123726569206415815)
> Tesla’s AI, running on our little AI4 computer, can now reach Torment II in Diablo

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| AI4 | ai4 | +0%, no liq @2.5m | +0%, no liq @5.7m | +0%, no liq @15.3m | +0%, no liq @60.0m | – | no |
| TI | tesla | +0%, no liq @2.4m | -32%, no liq @5.5m | -34%, no liq @15.2m | -35%, no liq @60.9m | – | no |
| TI | tesla | missed | missed | missed | missed | – | no |
| TI | tesla | +0%, no liq @2.2m | +0%, no liq @5.4m | -8%, no liq @15.0m | -8%, no liq @60.8m | – | no |
| TAI | tesla | +0%, no liq @1.9m | -12%, no liq @5.0m | -24%, no liq @15.7m | -24%, no liq @60.4m | – | no |
| AI4 | ai4 | +0%, no liq @1.8m | -7%, no liq @5.0m | -7%, no liq @15.7m | -7%, no liq @60.4m | – | no |
| TAI | tesla | missed | missed | missed | missed | – | no |
| TSI | tesla | +0%, no liq @1.4m | -4%, no liq @5.6m | -4%, no liq @15.2m | -4%, no liq @61.0m | – | no |
| TI | tesla | +0%, no liq @1.9m | +0%, no liq @5.1m | +0%, no liq @15.7m | +0%, no liq @60.4m | – | no |
| Diablo | diablo | +0%, no liq @1.4m | +0%, no liq @5.7m | +0%, no liq @15.2m | -0%, no liq @61.0m | – | no |
| Diablo | diablo | +0%, no liq @1.2m | -27%, no liq @5.5m | -27%, no liq @15.0m | -27%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 14 s | AI4 | AI4 | ai4 | price not recorded |  |  |  |  |
| 22 s | TI | Tesla Inu | tesla | price not recorded |  |  |  |  |
| 25 s | TI | Tesla Inu | tesla | price not recorded |  |  |  |  |
| 32 s | TI | Tesla Inu | tesla | price not recorded |  |  |  |  |
| 52 s | TAI | Tesla Artificial Inu | tesla | price not recorded |  |  |  |  |
| 53 s | AI4 | AI4 | ai4 | price not recorded |  |  |  |  |
| 56 s | TAI | Tesla Artificial Inu | tesla | price not recorded |  |  |  |  |
| 82 s | TSI | Tesla Super Inu | tesla | price not recorded |  |  |  |  |
| 180 s | TI | Tesla Inu | tesla | price not recorded |  |  |  |  |
| 270 s | Diablo | Diablo | diablo | price not recorded |  |  |  |  |
| 348 s | Diablo | Diablo | diablo | price not recorded |  |  |  |  |

## @cz_binance 2026-11-20 10:38:34 UTC (post 2123727696673026236)
> There are forces spreading negative narratives, with massive amounts of funding behind it. https://t.co/Ymy4sA0cJd

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-20 11:06:02 UTC (post 2123734610169454954)
> Literally all you have to do is Persist Forever, and you will win.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| PERSIST | forever, persist | missed | missed | missed | missed | – | no |
| PERSIST | forever, persist | missed | missed | missed | missed | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 35 s | PERSIST | Persist Forever | forever, persist | price not recorded |  |  |  |  |
| 35 s | PERSIST | Persist Forever | forever, persist | price not recorded |  |  |  |  |

## @cz_binance 2026-11-20 11:11:15 UTC (post 2123735923380965851)
> Price discovery happens first on chain. https://t.co/GGL8NsrIkP

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 11:19:25 UTC (post 2123737976710848580)
> Yes https://t.co/NAk6Emsump

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-20 12:11:31 UTC (post 2123751089707376971)
> 网上爆料一眼假，建议可以多关注下薄肌，黄毛，孙学理论，提升自我修养。

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-20 12:22:57 UTC (post 2123753964378439839)
> 大红果时代的第一颗大结果！ https://t.co/uN28PvP6Q6

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-20 13:15:11 UTC (post 2123767110606176532)
> To find the coin that will be the Biggest Household Name when we are in the middle of a Raging Bull Market… Find a community that acts as if

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| TRUMP | bull | +0%, no liq @1.1m | -0%, no liq @5.4m | -0%, no liq @15.1m | +0%, no liq @60.1m | – | no |
| TRUMP | bull | +0%, no liq @1.8m | -0%, no liq @5.0m | -0%, no liq @15.8m | -0%, no liq @60.7m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 231 s | TRUMP | The Crypto Bull | bull | +159% | +160% | -67% | -67% | +182% (64 s) |
| 382 s | TRUMP | The Crypto Bull | bull | -8% | -8% | -8% | -8% | +13% (42 s) |
| 600 s | BEARMKT | Bear Market | market | price not recorded |  |  |  |  |

## @saylor 2026-11-20 14:13:03 UTC (post 2123781672705360055)
> Bitcoin is the foundation of everything we do at Strategy. It gives people, companies and agents everywhere the power to hold, move and prog

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SA | agents | +0%, no liq @1.2m | -47%, no liq @5.5m | -47%, no liq @15.1m | -49%, no liq @61.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 480 s | SA | Super Agents | agents | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-20 15:35:24 UTC (post 2123802396686168289)
> 交易美股来火币！ https://t.co/U5Trov8XP9

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-20 15:39:04 UTC (post 2123803318476808632)
> TRX，人称小JST 😂 https://t.co/c9FtzkGi2w

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 16:06:15 UTC (post 2123810162071019606)
> The $1,000,000 Perps Open has officially begun! Traders on Pumpfun have 2 weeks to achieve the highest perps PnL to be in with a chance of w

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 16:06:16 UTC (post 2123810166768554352)
> Learn more about the $1M Perps Open: https://t.co/0D9w5V8eyI

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 16:06:18 UTC (post 2123810171583693065)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 16:06:20 UTC (post 2123810182069407768)
> https://t.co/zGb537JwBu

No matching launch in the next 10 minutes.

## @justinsuntron 2026-11-20 16:11:19 UTC (post 2123811434320871659)
> Riemann Hypothesis has been solved. @JustinSunPrize https://t.co/NErQ9ASUXT

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-20 16:15:20 UTC (post 2123812446745907359)
> The crypto communities that survive the next few months will go to Trillions.

No matching launch in the next 10 minutes.

## @saylor 2026-11-20 17:11:41 UTC (post 2123826627759264099)
> Remember why you ₿ought. https://t.co/UxYdpFJutx

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 17:17:07 UTC (post 2123827993382687217)
> Made with Grok @Bot https://t.co/b1rXfw9h4K

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 18:15:34 UTC (post 2123842705767977412)
> Cross margin and Pro mode are live on Pumpfun! - Cross margin: every position shares your full balance as margin - Add or remove margin on o

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 18:15:35 UTC (post 2123842710591402027)
> The $1,000,000 Perps Open is live. Learn more: https://t.co/0D9w5V8eyI

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 18:15:37 UTC (post 2123842715381281104)
> Who can trade Perps Hyperliquid is a third-party protocol, which https://t.co/CxsEJIFc8C does not operate. https://t.co/WWU97JhVgi is an app

No matching launch in the next 10 minutes.

## @Pumpfun 2026-11-20 18:15:39 UTC (post 2123842727301484663)
> https://t.co/jWtq7KeAHv

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 18:28:08 UTC (post 2123845867526574261)
> I was just thinking that (for myself) stupidity doesn’t count unless I’m also really obstinate about it

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 91 s | OI | Obstinate Inu | obstinate | price not recorded |  |  |  |  |

## @elonmusk 2026-11-20 18:30:35 UTC (post 2123846481488789866)
> Haven’t read it, but probably mostly (80% or so) accurate https://t.co/C4XWSywt7B

No matching launch in the next 10 minutes.

## @elonmusk 2026-11-20 18:34:02 UTC (post 2123847352582897719)
> This is where the smart people are https://t.co/9PRyK3Sx3i

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 29 s | SI | Smart Inu | smart | price not recorded |  |  |  |  |
| 55 s | SI | Smart Inu | smart | price not recorded |  |  |  |  |
| 105 s | Smartlon | Smart Elon | smart | +16% | -62% | -62% | -62% | +110% (95 s) |

## @elonmusk 2026-11-20 18:55:08 UTC (post 2123852660688494744)
> Hear me out: “Singularity dot Com”, a dating site for digital superintelligences …

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 73 s | SINGULARITY | Singularity.com | singularity | price not recorded |  |  |  |  |
| 104 s | Single SI | Singularity.com | singularity | price not recorded |  |  |  |  |
| 160 s | Singularity | Singularity.com | singularity | price not recorded |  |  |  |  |
| 529 s | SING | Singularity | singularity | +0% | +0% | +0% | +0% | +0% (2 s) |
| 536 s | Singular | SINGULARITY.COM | singularity | price not recorded |  |  |  |  |

## @a1lon9 2026-11-20 19:28:04 UTC (post 2123860949979320368)
> Why is Pumpfun running a perps competition in this market? Over 27% of the traders who signed up for the $1M Perps Open had never traded per

No matching launch in the next 10 minutes.

## @MustStopMurad 2026-11-20 19:29:53 UTC (post 2123861406655357176)
> SPX6900 will be the first ever memecoin to reach a market capitalization of a Trillion Dollars. Mark my words.

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| SPX6900 | spx6900 | missed | missed | missed | missed | – | no |
| MAPLE | market | +0%, no liq @1.7m | +0%, no liq @6.0m | +0%, no liq @15.7m | +0%, no liq @61.0m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 10 s | SPX6900 | SPX6900 | spx6900 | price not recorded |  |  |  |  |
| 520 s | MAPLE | maple market | market | price not recorded |  |  |  |  |

## @blknoiz06 2026-11-20 20:44:42 UTC (post 2123880234303062051)
> equities are trading like there's going to be war escalation this weekend or something its just straight down, ive seen crypto do this a lot

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 22:34:47 UTC (post 2123907939966861741)
> stay patient but remain ready to respond to new information https://t.co/TjGwXdVCD6

No matching launch in the next 10 minutes.

## @toly 2026-11-20 23:08:56 UTC (post 2123916530664841351)
> 🐜🐜🐜 https://t.co/ZCrVhy384n

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 23:10:33 UTC (post 2123916941501022208)
> gmihao brother we will weather the storm together https://t.co/lsFcKFPIA3 https://t.co/eiz2mafjSB

No matching launch in the next 10 minutes.

## @toly 2026-11-20 23:10:53 UTC (post 2123917021452837258)
> Proof of History has never been solved. Just saying.

No matching launch in the next 10 minutes.

## @toly 2026-11-20 23:13:27 UTC (post 2123917670148096323)
> 👑👑👑 https://t.co/2JZABd8LJz

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 23:13:30 UTC (post 2123917682906951870)
> bro dis shit deadass look like a shitcoin chart https://t.co/a8WdONkoFY

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 309 s | BOTSHIT | Bot Shit | shit | price not recorded |  |  |  |  |

## @toly 2026-11-20 23:15:40 UTC (post 2123918228347134029)
> 😭😭😭 https://t.co/28DbXsMNJK

No matching launch in the next 10 minutes.

## @toly 2026-11-20 23:17:48 UTC (post 2123918764794380309)
> 🐐🐐🐐 https://t.co/QS5YZOubIp

No matching launch in the next 10 minutes.

## @blknoiz06 2026-11-20 23:33:42 UTC (post 2123922764361023733)
> what we buyin chat

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| WHAT | buyin | missed | missed | missed | +0%, no liq @60.8m | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 266 s | WHAT | What we buyin | buyin | price not recorded |  |  |  |  |

## @cz_binance 2026-11-20 23:50:33 UTC (post 2123927005863563713)
> Wow, this is insane, and complete BS. I guess this is how they control "public perception"? https://t.co/rJvAhFlmmP

No matching launch in the next 10 minutes.

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
| SPACEX | spacex | +0%, no liq @1.3m | -13%, no liq @5.4m | -13%, no liq @15.6m | – | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 514 s | SPACEX | SpaceX Coin | spacex | price not recorded |  |  |  |  |

## @VitalikButerin 2026-11-26 06:59:30 UTC (post 2125846895822328103)
> Cleverness is knowing that the elevator close button (at least in the US) doesn't actually make the door close any faster. Wisdom is ignorin

post_match flags (DexScreener, recording only):

| Symbol | Matched | 1 min | 5 min | 15 min | 60 min | Highest liquidity | Reached $50,000 |
|---|---|---|---|---|---|---|---|
| WI | wisdom | missed | – | – | – | – | no |
| WI | wisdom | missed | – | – | – | – | no |

| Launched after | Symbol | Name | Matched | 1 min | 5 min | 15 min | 1 h | Peak (after) |
|---|---|---|---|---|---|---|---|---|
| 25 s | WI | wisdom inu | wisdom | price not recorded |  |  |  |  |
| 41 s | WI | wisdom inu | wisdom | price not recorded |  |  |  |  |

## @justinsuntron 2026-11-26 07:00:02 UTC (post 2125847026265149474)
> Sunday on the Main Stage. See you in Bangkok. 🇹🇭 https://t.co/x5xI3Yo3xV

No matching launch in the next 10 minutes.

