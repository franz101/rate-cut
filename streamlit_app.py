import streamlit as st

import requests
import pandas as pd
import websockets
import json
import asyncio 

polymarket_endpoint = "https://clob.polymarket.com"

@st.cache_data
def get_markets():
    markets = list()
    old_cursor = None
    new_cursor = "MA=="
    while old_cursor != new_cursor:
        old_cursor = new_cursor
        d = requests.get(f"{polymarket_endpoint}/markets?next_cursor={new_cursor}").json()
        new_cursor = d["next_cursor"]
        markets += d["data"]
        if new_cursor == 'LTE=':
            break
    return markets

def get_token_id(row):
    tokens = row["tokens"]
    for token in tokens:
        row[f"outcome_{token['outcome']}_price"] = token["price"]
        row[f"outcome_{token['outcome']}_id"] = token["token_id"]
    return row

markets = get_markets()
mf = pd.DataFrame(markets)
mf = mf[
    (mf["question"].str.contains(" interest rates")) &
    (mf["question"].str.contains(" September")) &
    (mf["active"]) &
    (mf["enable_order_book"]) &
    (mf["accepting_orders"]) &
    ~(mf["closed"])
]


def polymarket_get_bid_ask(token_id):
  ob = requests.get(f"{polymarket_endpoint}/book?token_id={token_id}").json()
  bids = ob["bids"]
  asks = ob["asks"]
  res = {}
  if bids:
    bid = bids[-1]
    res["bid_price"] = float(bid["price"] )
    res["bid_size"] = float(bid["size"])
  if asks:
    ask = asks[-1]
    res["ask_price"] = float(ask["price"] )
    res["ask_size"] = float(ask["size"])
  return res

mf = mf.apply(get_token_id, axis=1)
mf[["question","outcome_Yes_id"]]

kalshi_endpoint = "https://trading-api.kalshi.com/v1/cached/"

def kalshi_get_bid_ask(ticker_id="FED-24SEP-T5.00"):
  ob1 = requests.get(f"{kalshi_endpoint}series/FED/markets/770ff465-d3c0-441c-a3a4-3e22a76c5ada/order_book?ticker={ticker_id}").json()
  yes_bid = ob1["order_book"]["yes"]
  no_bid = ob1["order_book"]["no"]
  res = {}
  if yes_bid:
    yes_bid = yes_bid[-1]
    res["bid_price"] = yes_bid[0]/100
    res["bid_size"] = yes_bid[1]
  if no_bid:
    no_bid = no_bid[-1]
    yes_ask = 100 - no_bid[0]
    res["ask_price"] = yes_ask/100
    res["ask_size"] = no_bid[1]

  return res

# Dictionary to map tick size change descriptions to ticker IDs
ticksize_change_dict = {
    "Cut >25bps": "FEDDECISION-24SEP-C26",
    "Cut 25bps": "FEDDECISION-24SEP-C25",
    "Hike 0bps": "FEDDECISION-24SEP-H0",
    "Hike 25bps": "FEDDECISION-24SEP-H25",
    "Hike >25bps": "FEDDECISION-24SEP-H26"
}

# Dictionary to map rate target descriptions to ticker IDs
rate_target_dict = {
    "FF Sep18'24 4.875 ABOVE": "721095497",  # YES means above 4.875%
    "FF Sep18'24 4.875 BELOW_OR_EQUAL": "721095500",  # NO means below or equal to 4.875%
    "FF Sep18'24 5.125 ABOVE": "719418349",  # YES means above 5.125%
    "FF Sep18'24 5.125 BELOW_OR_EQUAL": "719418355",  # NO means below or equal to 5.125%
    "FF Sep18'24 5.375 ABOVE": "712857011",  # YES means above 5.375%
    "FF Sep18'24 5.375 BELOW_OR_EQUAL": "712857014"  # NO means below or equal to 5.375%
}



def get_ticker(conId: int):
    return f'smd+{conId}+{{"fields":["84", "86", "85", "88"],"backout":true}}'


async def forecast_trader_get_bid_ask(ticker_id):
  wss = 'wss://forecasttrader.interactivebrokers.com/portal.proxy/v1/etp/ws'

  s = requests.Session()
  s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
  s.get("https://forecasttrader.interactivebrokers.com/eventtrader/#/market-details?market=g2&id=658663572202409184.8751")
  r = s.get("https://forecasttrader.interactivebrokers.com/portal.proxy/v1/etp/iserver/auth/status")

  cookie_string = "; ".join([f"{name}={value}" for name, value in s.cookies.items()])
  headers = {
    'User-Agent': s.headers["User-Agent"],
    "cookie": cookie_string
  }
  async with websockets.connect(wss, extra_headers=headers) as websocket:
      m = await websocket.recv()
      await websocket.send("system")
      m = await websocket.recv()
      m = await websocket.recv()
      await websocket.recv()
      tickers = [ticker_id]
      for ticker in tickers:
          await websocket.send(get_ticker(ticker))
      res =  await websocket.recv()
      contract_data = json.loads(res)

      bid = contract_data.get("84", "nan").replace(",", "")
      ask = contract_data.get("86", "nan").replace(",", "")
      bid_size = contract_data.get("88", "nan").replace(",", "")
      ask_size = contract_data.get("85", "nan").replace(",", "")
      return {
          "bid_price": float(bid),
          "ask_price": float(ask),
          "bid_size": float(bid_size),
          "ask_size": float(ask_size)}



@st.cache_data
def get_fedrate_ib():
  s = requests.Session()
  s.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
  d = s.get("https://forecasttrader.interactivebrokers.com/tws.proxy/public/hmds/forecastIndex?conid=658663572&period=5years&step=1month&exchange=FORECASTX&outsideRth=true&secType=IND")
  j = d.json()
  fed_rate_ib = pd.DataFrame(j)
  fed_rate_ib["ts"] = pd.to_datetime(fed_rate_ib["time"],unit="s")
  return fed_rate_ib["avg"].iloc[-1]

@st.cache_data
def get_sofr_prediction():
  d= requests.post("https://scanner.tradingview.com/futures/scan",
      json= {'columns': ['pricescale', 'minmov', 'minmove2', 'fractional', 'expiration', 'close', 'name', 'currency'],
              'filter': [{'left': 'close', 'operation': 'nempty'}, {'left': 'expiration', 'operation': 'nempty'}],
              'sort': {'sortBy': 'expiration', 'sortOrder': 'asc'},
                'markets': ['futures'],
                'index_filters': [{'name': 'root', 'values': ['CME:SR3']}]},

      headers =  {
          "Accept": "application/json",
          "Accept-Language": "en-US,en;q=0.9",
          "Cache-Control": "no-cache",
          "Content-Type": "text/plain;charset=UTF-8",
          "Pragma": "no-cache",
          "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
      },

  ).json()
  return 100 - d["data"][0]["d"][-3]

sofr_rate =  get_sofr_prediction()
fed_rate_ib = get_fedrate_ib()
st.title("Interest Rate Comparison Dashboard")
st.header("Current Rates")
col1, col2 = st.columns(2)
col1.metric("Current Fed Rate", f"{get_fedrate_ib():.2f}%")
col2.metric("SOFR Implied Rate for September", f"{sofr_rate:.2f}%")
async def print_data():
  market_1_data = {}
  for desc, ticker_id in rate_target_dict.items():
    market_1_data[desc] = await forecast_trader_get_bid_ask(ticker_id)

  market_2_data = {} 
  for i, row in mf[["question","outcome_Yes_id"]].iterrows():
    market_2_data[row["question"]] = polymarket_get_bid_ask(row["outcome_Yes_id"])
    

  market_3_data = {
  }
  for desc, ticker_id in ticksize_change_dict.items():
    market_3_data[desc] =  kalshi_get_bid_ask(ticker_id)

  # Organize the data into a comparison table
  comparison_table = {
      'Rate Outcome': [],
      'Market 1': [],
      'Market 2': [],
      'Market 3': []
  }


  rate_outcomes = [
      {
          'Rate Outcome': 'Cut >25bps',
          'Market 1': ["FF Sep18'24 4.875 ABOVE"],
          'Market 2': ['Fed decreases interest rates by 50+ bps after September 2024 meeting?'],
          'Market 3': ['Cut >25bps']
      },
      {
          'Rate Outcome': 'Cut 25bps',
          'Market 1': ["FF Sep18'24 5.125 ABOVE"],
          'Market 2': ['Fed decreases interest rates by 25 bps after September 2024 meeting?'],
          'Market 3': ['Cut 25bps']
      },
      {
          'Rate Outcome': 'No Change',
          'Market 1': ["FF Sep18'24 5.375 ABOVE"],
          'Market 2': ['No change in Fed interest rates after 2024 September meeting?'],
          'Market 3': ['Hike 0bps']
      },
      {
          'Rate Outcome': 'Hike 25bps or more',
          'Market 1': ["FF Sep18'24 5.375 BELOW_OR_EQUAL", "FF Sep18'24 5.125 BELOW_OR_EQUAL"],
          'Market 2': ['Fed increases interest rates by 25+ bps after September 2024 meeting?'],
          'Market 3': ['Hike 25bps', 'Hike >25bps']
      }
  ]


  # Populate the comparison table with data
  for outcome in rate_outcomes:
      comparison_table['Rate Outcome'].append(outcome['Rate Outcome'])
      
      # Fetch Market 1 data
      market_1_entries = []
      for desc in outcome['Market 1']:
          data = market_1_data[desc]
          market_1_entries.append({desc: data})
      comparison_table['Market 1'].append(market_1_entries)
      
      # Fetch Market 2 data
      market_2_entries = []
      for question in outcome['Market 2']:
          data = market_2_data[question]
          market_2_entries.append({question: data})
      comparison_table['Market 2'].append(market_2_entries)
      
      # Fetch Market 3 data
      market_3_entries = []
      for desc in outcome['Market 3']:
          data = market_3_data[desc]
          market_3_entries.append({desc: data})
      comparison_table['Market 3'].append(market_3_entries)
  

  print("CURRENT RATE", fed_rate_ib["avg"].iloc[-1])
  print("SOFR IMPLIED RATE FOR SEPTEMBER",sofr_rate)

  for i in range(len(comparison_table['Rate Outcome'])):
      print(f"Rate Outcome: {comparison_table['Rate Outcome'][i]}")
      print("Market 1 Data:")
      for item in comparison_table['Market 1'][i]:
          print(item)
      print("Market 2 Data:")
      for item in comparison_table['Market 2'][i]:
          print(item)
      print("Market 3 Data:")
      for item in comparison_table['Market 3'][i]:
          print(item)
      print("\n")

  comparison_data = []
  for outcome in rate_outcomes:
      row = {'Rate Outcome': outcome['Rate Outcome']}
      
      for market_num, market_data in enumerate([market_1_data, market_2_data, market_3_data], start=1):
          market_key = f'Market {market_num}'
          market_probabilities = []
          for desc in outcome[market_key]:
              data = market_data.get(desc, {})
              if 'bid_price' in data and 'ask_price' in data:
                  probability = (data['bid_price'] + data['ask_price']) / 2
                  market_probabilities.append(probability)
          
          if market_probabilities:
              row[market_key] = f"{sum(market_probabilities) / len(market_probabilities):.2%}"
          else:
              row[market_key] = "N/A"
      
      comparison_data.append(row)
  comparison_df = pd.DataFrame(comparison_data)
  st.table(comparison_df)