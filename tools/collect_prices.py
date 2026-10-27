#!/usr/bin/env python3
"""
Pehle Dekho - price refresher.

The app's stored prices were baked in at build time and go stale within days:
an audit against live quotes found four of twelve more than 10% off, and nine of
twelve more than 2% off. This publishes data/prices.json with the last close and
the previous close, so the app can show a current price and a real 1-day move
without waiting for a rebuild.

Source: Yahoo Finance, one call per symbol. Rate-limited on purpose - a burst
gets 429'd and the whole run is wasted.
"""
import json, os, sys, time, datetime, urllib.request, urllib.parse

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'prices.json')
UNI = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe.json')
HDR = {'User-Agent': 'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/120 Safari/537.36'}
PAUSE = 0.45
RETRY = 3


def yahoo(sym):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/' +
           urllib.parse.quote(sym) + '.NS?range=5d&interval=1d')
    last = None
    for a in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=HDR)
            d = json.loads(urllib.request.urlopen(req, timeout=20).read())
            r = d['chart']['result'][0]
            cl = [x for x in r['indicators']['quote'][0]['close'] if x is not None]
            if not cl:
                return None
            return {'last': round(cl[-1], 2),
                    'prev': round(cl[-2], 2) if len(cl) > 1 else None,
                    'day': str(datetime.date.fromtimestamp(r['meta']['regularMarketTime']))}
        except Exception as e:
            last = e
            time.sleep(1.5 * (2 ** a))
    print('  fail', sym, last)
    return None


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 525
    try:
        u = json.load(open(UNI, encoding='utf-8'))
    except Exception as e:
        print('universe not found:', e); return
    tickers = []
    for x in u:
        if isinstance(x, (list, tuple)) and x: tickers.append(str(x[0]))
        elif isinstance(x, dict): tickers.append(str(x.get('tk') or ''))
        elif isinstance(x, str): tickers.append(x)
    tickers = [t for t in tickers if t][:limit]

    prev = {}
    try:
        prev = json.load(open(OUT, encoding='utf-8')).get('prices', {})
    except Exception:
        pass

    prices, ok = {}, 0
    for i, tk in enumerate(tickers):
        d = yahoo(tk)
        time.sleep(PAUSE)
        if d:
            prices[tk] = d
            ok += 1
        if (i + 1) % 50 == 0:
            print('  %d/%d done, %d priced' % (i + 1, len(tickers), ok))

    for k, v in prev.items():
        if k not in prices:
            prices[k] = v

    payload = {'date': datetime.date.today().isoformat(), 'source': 'Yahoo Finance',
               'requested': len(tickers), 'ok': ok, 'prices': prices,
               'note': 'Last close and previous close. Nothing estimated.'}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\npriced %d of %d (kept %d from before)' % (ok, len(tickers), len(prices) - ok))


if __name__ == '__main__':
    main()
