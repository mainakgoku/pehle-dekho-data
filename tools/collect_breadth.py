#!/usr/bin/env python3
"""Today's breadth and today's sector moves - published for the app to read.

WHY THIS EXISTS
  The app answered "why is the market down today" with six-month figures,
  because loading today's move for all 525 stocks on a phone is 525 network
  calls - minutes of work, and Yahoo throttles hard. So the CLOUD does it, once
  an hour, and publishes one small file. The phone reads that instead.

WHAT IT PUBLISHES  (data/live-breadth.json)
  today      up / down / flat counts across the tracked universe
  sectors    today's average move per sector
  asOf       the timestamp, so a stale file can never be shown as today's
  indices    Nifty / Sensex / Bank Nifty, so the app can cross-check

HONESTY RULES
  - if a stock's price cannot be fetched it is counted as unknown, never guessed
  - if the whole run fails, the file records that rather than a stale count
  - a file older than the trading day must not be presented as today's
"""
import json, os, sys, urllib.request, datetime, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

IDX = {'nifty': '^NSEI', 'sensex': '^BSESN', 'banknifty': '^NSEBANK'}


def universe():
    try:
        with open(os.path.join(DATA, 'universe.json')) as f:
            return json.load(f)
    except Exception:
        return []


def quote(sym):
    """Latest price and previous close -> today's % move."""
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/%s'
           '?range=5d&interval=1d' % sym)
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    res = d['chart']['result'][0]
    meta = res.get('meta') or {}
    # TODAY's move is the last close against the one before it. Do NOT use
    # chartPreviousClose on a multi-day range - that is the close before the
    # whole window, which gave a 5-day move wearing today's label.
    q = (res['indicators']['quote'] or [{}])[0]
    cl = [c for c in (q.get('close') or []) if c is not None]
    price = meta.get('regularMarketPrice')
    if len(cl) >= 2:
        price, prev = cl[-1], cl[-2]
    else:
        prev = meta.get('previousClose') or meta.get('chartPreviousClose')
    if price is None or not prev:
        return None
    return {'p': float(price), 'chg': (float(price) / float(prev) - 1) * 100}


def main():
    uni = universe()
    if not uni:
        print('no universe.json - nothing to scan')
        return 0

    up = dn = flat = unknown = 0
    sec_sum, sec_n = {}, {}
    rows = []
    for row in uni:
        tk, sym = row.get('tk'), row.get('sym')
        sec = row.get('sector') or 'Other'
        if not tk or not sym:
            continue
        try:
            q = quote(sym)
        except Exception:
            unknown += 1
            continue
        if not q:
            unknown += 1
            continue
        c = q['chg']
        if c > 0.05:
            up += 1
        elif c < -0.05:
            dn += 1
        else:
            flat += 1
        sec_sum[sec] = sec_sum.get(sec, 0.0) + c
        sec_n[sec] = sec_n.get(sec, 0) + 1
        rows.append({'tk': tk, 'chg': round(c, 2), 'sector': sec})
        time.sleep(0.12)          # Yahoo throttles hard - be kind

    sectors = [{'sec': s, 'avg': round(sec_sum[s] / sec_n[s], 2), 'n': sec_n[s]}
               for s in sec_sum if sec_n.get(s)]
    sectors.sort(key=lambda x: -x['avg'])

    indices = {}
    for name, sym in IDX.items():
        try:
            q = quote(sym)
            if q:
                indices[name] = {'p': round(q['p'], 2), 'chg': round(q['chg'], 2)}
        except Exception:
            pass
        time.sleep(0.3)

    out = {
        'asOf': datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00', 'Z'),
        'asOfIST': (datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(hours=5, minutes=30)).strftime('%Y-%m-%d %H:%M'),
        'today': {'up': up, 'down': dn, 'flat': flat, 'unknown': unknown,
                  'total': up + dn + flat},
        'sectors': sectors,
        'indices': indices,
        'best': sorted(rows, key=lambda x: -x['chg'])[:8],
        'worst': sorted(rows, key=lambda x: x['chg'])[:8],
        'note': ('Counts are TODAY\u2019s moves across the tracked universe, '
                 'computed in the cloud. A file from an earlier day is not today\u2019s.'),
    }
    with open(os.path.join(DATA, 'live-breadth.json'), 'w') as f:
        json.dump(out, f, indent=1)
    print('today: %d up, %d down, %d flat (%d unknown) | sectors %d | asOf %s'
          % (up, dn, flat, unknown, len(sectors), out['asOfIST']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
