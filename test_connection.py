from dotenv import load_dotenv
import os

load_dotenv(r'C:\Users\glmar\.env')

from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs

key = os.getenv('PRIVATE_KEY')
if not key:
    print("ERROR: PRIVATE_KEY not found in .env")
    exit()

addr = Account.from_key(key).address
print("Your wallet address:", addr)
print("Proxy wallet:        0xa1823f3BacCEEF4e4358Af25D2686A03cEe930f5")

# Try signature_type=1 with YOUR address as funder
print("\nTrying signature_type=1, funder=your address...")
try:
    client = ClobClient('https://clob.polymarket.com', key=key, chain_id=137,
                        signature_type=1, funder=addr)
    client.set_api_creds(client.create_or_derive_api_creds())
    markets = client.get_sampling_simplified_markets()
    for m in markets.get('data', []):
        tokens = m.get('tokens', [])
        if not tokens: continue
        price = float(tokens[0].get('price', 0))
        if not (0.05 < price < 0.95): continue
        token_id = tokens[0]['token_id']
        price = round(price, 2)
        shares = round(1.0 / price, 4)
        resp = client.create_and_post_order(OrderArgs(token_id=token_id, price=price, size=shares, side='BUY'))
        print("ORDER PLACED:", resp)
        break
except Exception as e:
    print("Failed:", str(e)[:120])
