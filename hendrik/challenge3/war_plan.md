1. create small minimalistic ts bun api 
2. get my rounds: curl 'https://api.ainm.no/astar-island/my-rounds' \
   -H 'accept: */*' \
   -H 'accept-language: en-US,en;q=0.9' \
   -b 'access_token=REDACTED_TOKEN' \
   -H 'origin: https://app.ainm.no' \
   -H 'priority: u=1, i' \
   -H 'referer: https://app.ainm.no/' \
   -H 'sec-ch-ua: "Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"' \
   -H 'sec-ch-ua-mobile: ?0' \
   -H 'sec-ch-ua-platform: "Linux"' \
   -H 'sec-fetch-dest: empty' \
   -H 'sec-fetch-mode: cors' \
   -H 'sec-fetch-site: same-site' \
   -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

it includes ALL rounds we have played, you can get initial_grid from it
3. use this to get predicions: curl 'https://api.ainm.no/astar-island/my-predictions/795bfb1f-54bd-4f39-a526-9868b36f7ebd' \
   -H 'accept: */*' \
   -H 'accept-language: en-US,en;q=0.9' \
   -b 'access_token=REDACTED_TOKEN' \
   -H 'origin: https://app.ainm.no' \
   -H 'priority: u=1, i' \
   -H 'referer: https://app.ainm.no/' \
   -H 'sec-ch-ua: "Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"' \
   -H 'sec-ch-ua-mobile: ?0' \
   -H 'sec-ch-ua-platform: "Linux"' \
   -H 'sec-fetch-dest: empty' \
   -H 'sec-fetch-mode: cors' \
   -H 'sec-fetch-site: same-site' \
   -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

4. use this to get queries: curl 'https://api.ainm.no/astar-island/my-queries/795bfb1f-54bd-4f39-a526-9868b36f7ebd' \
   -H 'accept: */*' \
   -H 'accept-language: en-US,en;q=0.9' \
   -b 'access_token=REDACTED_TOKEN' \
   -H 'origin: https://app.ainm.no' \
   -H 'priority: u=1, i' \
   -H 'referer: https://app.ainm.no/' \
   -H 'sec-ch-ua: "Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"' \
   -H 'sec-ch-ua-mobile: ?0' \
   -H 'sec-ch-ua-platform: "Linux"' \
   -H 'sec-fetch-dest: empty' \
   -H 'sec-fetch-mode: cors' \
   -H 'sec-fetch-site: same-site' \
   -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'

5. use this to get prediction, ground truth + initial grid:
   curl 'https://api.ainm.no/astar-island/analysis/795bfb1f-54bd-4f39-a526-9868b36f7ebd/0' \
   -H 'accept: */*' \
   -H 'accept-language: en-US,en;q=0.9' \
   -b 'access_token=REDACTED_TOKEN' \
   -H 'origin: https://app.ainm.no' \
   -H 'priority: u=1, i' \
   -H 'referer: https://app.ainm.no/' \
   -H 'sec-ch-ua: "Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"' \
   -H 'sec-ch-ua-mobile: ?0' \
   -H 'sec-ch-ua-platform: "Linux"' \
   -H 'sec-fetch-dest: empty' \
   -H 'sec-fetch-mode: cors' \
   -H 'sec-fetch-site: same-site' \
   -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36'


sooo, what u rly need is data for each round, so basically do it like this:
1. do step 2. get round ids
2. then for each round, get step 5, 4 and 3. I think there may be some duplicate data in there, so dedup

all of this should be done in ts script and it should output 13 json files, 1 for each round
last round is running
in output json, I expect these fields:

round_id
round_number
status
round_weight
round_score
seed_scores
rank
initial_grid
prediction
ground_truth
queries
argmax_grid
confidence_grid

docs for the challenge: /home/hendrik/Documents/agentic-avengers-nm-ai/hendrik/raw_docs_norgesgruppen.md




OVERLAPPING AREAS IN QUERY RESPONSES:
This is really telling:

Overall: 74.6% agreement between two observations of the same cell. So ~25% of cells change outcome between sim runs.

By terrain stability:
- Mountain: 100% — perfectly deterministic
- Ocean: 98.3% — nearly static (the 1.7% is probably edge cells)
- Plains: 82.1% — mostly stays plains
- Forest: 75.5% — fairly stable
- Settlement: 32.1% — highly volatile! 2/3 of the time it's something different on the next sim
- Port: 16.6% — extremely volatile
- Ruin: 5% — almost never the same twice (ruins are rare flukes)

When cells disagree, the top 3:
1. Settlement ↔ Plains (44%) — settlements either survive or collapse to empty land
2. Forest ↔ Plains (21%) — forest either persists or gets cleared
3. Settlement ↔ Forest (18%) — settlements get overtaken by forest or vice versa

This confirms: the simulation is fundamentally about will settlements survive or die, and everything else follows from that. The stochasticity is
concentrated in settlement fate — the rest is mostly deterministic.

