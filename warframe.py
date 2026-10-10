import asyncio
import time
import os
from datetime import datetime, timezone

import httpx

mods = [
    'ytyutj'
    'primed_continuity', 'transient_fortitude', 'primed_flow', 'blind_rage', 'primed_ravage',
    'primed_ammo_stock', 'primed_bane_of_corpus', 'primed_bane_of_grineer', 'primed_bane_of_infested',
    'primed_bane_of_corrupted', 'primed_animal_instinct', 'primed_redirection', 'primed_reach',
    'primed_regen', 'primed_rubedo_lined_barrel', 'primed_charged_shell', 'primed_chilling_grasp',
    'primed_cleanse_corpus', 'primed_cleanse_grineer', 'primed_cleanse_infested', 'primed_cleanse_corrupted',
    'primed_convulsion', 'primed_cryo_rounds', 'primed_deadly_efficiency', 'primed_dual_rounds',
    'primed_expel_corpus', 'primed_expel_grineer', 'primed_expel_infested', 'primed_expel_corrupted',
    'primed_fast_hands', 'primed_fever_strike', 'primed_firestorm', 'primed_fulmination',
    'primed_heated_charge', 'primed_heavy_trauma', 'primed_magazine_warp', 'primed_morphic_transformer',
    'primed_pack_leader', 'primed_pistol_ammo_mutation', 'primed_pistol_gambit', 'primed_point_blank',
    'primed_pressure_point', 'primed_quickdraw', 'primed_rifle_ammo_mutation', 'primed_shotgun_ammo_mutation',
    'primed_slip_magazine', 'primed_smite_corpus', 'primed_smite_grineer', 'primed_smite_infested',
    'primed_smite_corrupted', 'primed_sniper_ammo_mutation', 'primed_tactical_pump', 'primed_target_cracker',
    'galvanized_aptitude', 'galvanized_acceleration', 'galvanized_chamber', 'galvanized_crosshairs',
    'galvanized_diffusion', 'galvanized_hell',
]

BASE_URL = "https://api.warframe.market/v2"
REQUESTS_PER_SECOND = 7      # documented API limit
MAX_RETRIES = 3
TIMEOUT = 15.0
ONLINE_STATUSES = {"ingame", "online"}   # ignore offline sellers/buyers
RANK = None                  # None = any rank, 0 = unranked only, 10 = max rank, etc.


class RateLimiter:
    def __init__(self, per_second):
        self._interval = 1.0 / per_second
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock: # when the scrape method receives this lock, it'll enter the code below
            now = time.monotonic()
            delay = self._next - now
            if delay > 0: # the first request will have negative value, so it'll skip the delay
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next = now + self._interval

    async def penalize(self, seconds):
        # This will change _next to whichever's larger, the current delay time, or the backoff period received by the server
        async with self._lock:
            self._next = max(self._next, time.monotonic() + seconds)


async def scrape_mod(mod, client, limiter):
    url = f"{BASE_URL}/orders/item/{mod}"

    for attempt in range(1, MAX_RETRIES + 1):
        await limiter.wait()
        try:
            resp = await client.get(url)

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2))
                print(f"[{datetime.now()}] Rate limited on {mod}, backing off {retry_after}s")
                await limiter.penalize(retry_after)
                continue
            if resp.status_code == 404:
                print(f"[{datetime.now()}] {mod}: not found")
                return None

            resp.raise_for_status()
            orders = resp.json().get("data") or []

            def usable(o):
                if (o.get("user") or {}).get("status") not in ONLINE_STATUSES:
                    return False
                return RANK is None or o.get("rank", 0) == RANK

            sells = [o["platinum"] for o in orders if o.get("type") == "sell" and usable(o)]
            buys = [o["platinum"] for o in orders if o.get("type") == "buy" and usable(o)]

            if not sells or not buys:
                print(f"[{datetime.now()}] {mod}: missing online sell or buy orders, skipping")
                return None

            seller_price = min(sells)   # cheapest you can buy at
            buyer_price = max(buys)     # highest you can sell at
            profit = buyer_price - seller_price
            print(f"[{datetime.now()}] {mod}: Seller={seller_price}, Buyer={buyer_price}, Profit={profit}")
            return {"mod": mod, "seller_price": seller_price,
                    "buyer_price": buyer_price, "profit": profit}

        except (httpx.HTTPError, ValueError, KeyError) as e:
            print(f"[{datetime.now()}] Error on {mod} (attempt {attempt}/{MAX_RETRIES}): {e!r}")
            await asyncio.sleep(0.5 * attempt)

    print(f"[{datetime.now()}] Giving up on {mod}")
    return None

import os

async def upload(results):
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    now = datetime.now(timezone.utc).isoformat()
    rows = [{**r, "updated_at": now} for r in results]
    history = [{**r, "recorded_at": now} for r in results]

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        # upsert latest snapshot
        r = await client.post(
            f"{base}/rest/v1/mod_prices?on_conflict=mod",
            json=rows,
            headers={"Prefer": "resolution=merge-duplicates"},
        )
        r.raise_for_status()
        # append to history
        r = await client.post(f"{base}/rest/v1/mod_price_history", json=history)
        r.raise_for_status()

async def main():
    start = time.time()
    limiter = RateLimiter(REQUESTS_PER_SECOND)
    headers = {"Accept": "application/json", "Language": "en", "Platform": "pc"}

    async with httpx.AsyncClient(headers=headers, timeout=TIMEOUT, http2=False) as client:
        responses = await asyncio.gather(*(scrape_mod(m, client, limiter) for m in mods))

    results = sorted((r for r in responses if r), key=lambda r: r["profit"], reverse=True)
    failed = sum(1 for r in responses if r is None)

    print("\nFinal Results:")
    for r in results:
        print(f"Mod: {r['mod']}, Seller: {r['seller_price']}p, Buyer: {r['buyer_price']}p, Profit: {r['profit']}p")

    await upload(results)
    
    print(f"\nCompleted in {time.time() - start:.2f} seconds")
    print(f"Failed/skipped mods: {failed}")


if __name__ == "__main__":
    asyncio.run(main())