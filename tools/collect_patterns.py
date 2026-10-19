#!/usr/bin/env python3
"""Scan the tracked universe for chart patterns, on ANY timeframe.

Runs on a schedule (GitHub Actions). This is the background half: the phone
cannot fetch intraday bars for 525 stocks - Yahoo would throttle it and it
would take minutes - so the CLOUD scans and publishes, and the app reads.

Timeframes
  15m  range=5d   interval=15m    (Yahoo keeps ~5 days of 15-minute bars)
  1h   range=1mo  interval=1h
  4h   aggregated from the 1-hour bars (Yahoo serves no 4h interval)
  1d   range=6mo  interval=1d

HONESTY RULES
  - never invent a pattern; if the bars cannot be fetched, write nothing for it
  - a head-and-shoulders needs a neckline break, or it is not reported
  - short candle patterns work intraday; the long formations need more history
    than 15-minute data holds, so they are only reported where the data supports
    them
"""
import json, os, sys, urllib.request, urllib.error, datetime, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

# timeframe -> (yahoo range, yahoo interval, label)
TIMEFRAMES = {
    '15m': ('5d',  '15m', '15-minute'),
    '1h':  ('1mo', '1h',  '1-hour'),
    '4h':  ('1mo', '1h',  '4-hour'),   # built by aggregating the 1h bars
    '1d':  ('6mo', '1d',  'daily'),
}


def universe():
    try:
        with open(os.path.join(DATA, 'universe.json')) as f:
            return json.load(f)
    except Exception:
        return []


def bars(sym, rng, interval):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/%s'
           '?range=%s&interval=%s' % (sym, rng, interval))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=25) as r:
        d = json.load(r)
    res = d['chart']['result'][0]
    q = res['indicators']['quote'][0]
    ts = res.get('timestamp') or []
    out = []
    for i, c in enumerate(q.get('close') or []):
        if c is None:
            continue
        out.append({'c': float(c),
                    'h': float((q.get('high') or [c])[i] or c),
                    'l': float((q.get('low') or [c])[i] or c),
                    't': ts[i] if i < len(ts) else None})
    return out


def to_4h(b):
    """Four 1-hour bars make one 4-hour bar. Yahoo serves no 4h interval."""
    out = []
    for i in range(0, len(b) - 3, 4):
        grp = b[i:i+4]
        out.append({'c': grp[-1]['c'],
                    'h': max(x['h'] for x in grp),
                    'l': min(x['l'] for x in grp),
                    't': grp[0]['t']})
    return out


def pct(a, b):
    return (a / b - 1) * 100 if b else 0


def detect(b):
    """Patterns visible in this bar series. Timeframe-agnostic by design."""
    found = []
    c = [x['c'] for x in b]
    n = len(c)
    if n < 30:
        return found
    last, prev = c[-1], c[-2]

    # breakout / breakdown of the recent range
    look = c[-40:-1] if n > 45 else c[:-1]
    if len(look) >= 10:
        hi, lo = max(look), min(look)
        if prev <= hi < last:
            found.append(('Breakout above range', 'bullish', 'fresh',
                          'closed above the range high of %.2f' % hi))
        if prev >= lo > last:
            found.append(('Breakdown below range', 'bearish', 'fresh',
                          'closed below the range low of %.2f' % lo))

    if n < 45:
        return found
    win = c[-60:]
    m = len(win)
    hiP, loP = [], []
    for i in range(2, m - 2):
        if win[i] >= win[i-1] and win[i] >= win[i-2] and win[i] >= win[i+1] and win[i] >= win[i+2]:
            hiP.append(i)
        if win[i] <= win[i-1] and win[i] <= win[i-2] and win[i] <= win[i+1] and win[i] <= win[i+2]:
            loP.append(i)
    for a in range(len(hiP) - 1):
        i1, i2 = hiP[a], hiP[a+1]
        if i2 - i1 < 5 or abs(pct(win[i1], win[i2])) >= 3:
            continue
        if pct(min(win[i1:i2+1]), win[i2]) < -3:
            found.append(('Double top', 'bearish', 'possible',
                          'two highs near %.2f with a dip between' % win[i2]))
            break
    for a in range(len(loP) - 1):
        j1, j2 = loP[a], loP[a+1]
        if j2 - j1 < 5 or abs(pct(win[j1], win[j2])) >= 3:
            continue
        if pct(max(win[j1:j2+1]), win[j2]) > 3:
            found.append(('Double bottom', 'bullish', 'possible',
                          'two lows near %.2f with a bounce between' % win[j2]))
            break
    for k in range(len(hiP) - 2):
        i1, i2, i3 = hiP[k], hiP[k+1], hiP[k+2]
        h1, h2, h3 = win[i1], win[i2], win[i3]
        if abs(pct(h1, h3)) < 2.5 and pct(h2, h1) > 4 and pct(h2, h3) > 4:
            neck = max(min(win[i1:i2+1]), min(win[i2:i3+1]))
            if win[m-1] < neck:
                found.append(('Head and shoulders', 'bearish', 'possible',
                              'head %.1f%% above the shoulders, neckline broken' % pct(h2, h1)))
                break
    for k in range(len(loP) - 2):
        j1, j2, j3 = loP[k], loP[k+1], loP[k+2]
        l1, l2, l3 = win[j1], win[j2], win[j3]
        if abs(pct(l1, l3)) < 2.5 and pct(l2, l1) < -4 and pct(l2, l3) < -4:
            neck = min(max(win[j1:j2+1]), max(win[j2:j3+1]))
            if win[m-1] > neck:
                found.append(('Inverse head and shoulders', 'bullish', 'possible',
                              'neckline reclaimed at %.2f' % neck))
                break
    return found


def scan(tf, uni, seen):
    rng, interval, label = TIMEFRAMES[tf]
    alerts, scanned, failed = [], 0, 0
    for row in uni:
        tk, sym = row.get('tk'), row.get('sym')
        if not tk or not sym:
            continue
        try:
            b = bars(sym, rng, interval)
            if tf == '4h':
                b = to_4h(b)
            scanned += 1
        except Exception:
            failed += 1
            continue
        for pat, side, conf, note in detect(b):
            key = '%s|%s|%s' % (tk, pat, tf)
            if seen.get(key):
                continue
            seen[key] = datetime.date.today().isoformat()
            alerts.append({'tk': tk, 'pattern': pat, 'side': side,
                           'confidence': conf, 'note': note, 'timeframe': tf,
                           'date': datetime.date.today().isoformat()})
        time.sleep(0.12)          # be kind to Yahoo - it throttles hard
    return alerts, scanned, failed


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    uni = universe()
    if not uni:
        print('no universe.json - nothing to scan')
        return 0
    try:
        with open(os.path.join(DATA, 'pattern-seen.json')) as f:
            seen = json.load(f)
    except Exception:
        seen = {}
    tfs = [only] if only else list(TIMEFRAMES.keys())
    summary = {}
    for tf in tfs:
        if tf not in TIMEFRAMES:
            continue
        alerts, scanned, failed = scan(tf, uni, seen)
        out = {'generated': datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),
               'timeframe': tf, 'label': TIMEFRAMES[tf][2],
               'scanned': scanned, 'failed': failed, 'alerts': alerts}
        with open(os.path.join(DATA, 'pattern-alerts-%s.json' % tf), 'w') as f:
            json.dump(out, f, indent=1)
        # keep the daily file at its old name so nothing that reads it breaks
        if tf == '1d':
            with open(os.path.join(DATA, 'pattern-alerts.json'), 'w') as f:
                json.dump(out, f, indent=1)
        summary[tf] = len(alerts)
        print('%-4s %-10s scanned %d, failed %d, NEW alerts %d' % (tf, TIMEFRAMES[tf][2], scanned, failed, len(alerts)))
    with open(os.path.join(DATA, 'pattern-seen.json'), 'w') as f:
        json.dump(seen, f, indent=1)
    # an index the app can read to know what exists
    with open(os.path.join(DATA, 'pattern-timeframes.json'), 'w') as f:
        json.dump({'generated': datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00","Z"),
                   'timeframes': [{'id': k, 'label': TIMEFRAMES[k][2],
                                   'file': 'pattern-alerts-%s.json' % k,
                                   'new': summary.get(k, 0)} for k in TIMEFRAMES]}, f, indent=1)
    print('done', summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
