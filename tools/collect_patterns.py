#!/usr/bin/env python3
"""Scan the tracked universe for chart patterns and store any NEW ones.

Runs on a schedule (GitHub Actions, hourly during market hours). This is the
"background" half of the pattern alerts: the phone does not have to be awake,
because the scanning happens in the cloud.

It detects the same patterns the app does, from daily closes, and writes only
what is genuinely NEW since the last run - so the alerts file is a list of
changes, not a repeated dump of everything.

HONESTY RULES
  - never invent a pattern; if the data cannot be fetched, write nothing
  - a pattern with no neckline break is not reported
  - every entry says how strong the evidence is
"""
import json, os, sys, urllib.request, datetime

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'pattern-alerts.json')
SEEN = os.path.join(os.path.dirname(__file__), '..', 'data', 'pattern-seen.json')
HIST = os.path.join(os.path.dirname(__file__), '..', 'data', 'archive')

# the tracked universe: ticker -> Yahoo symbol
def universe():
    p = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe.json')
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return []


def closes(sym, rng='6mo'):
    url = ('https://query1.finance.yahoo.com/v8/finance/chart/%s'
           '?range=%s&interval=1d' % (sym, rng))
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)
    res = d['chart']['result'][0]
    q = res['indicators']['quote'][0]
    out = []
    for i, c in enumerate(q.get('close') or []):
        if c is None:
            continue
        out.append({'c': float(c),
                    'h': float((q.get('high') or [c])[i] or c),
                    'l': float((q.get('low') or [c])[i] or c)})
    return out


def pct(a, b):
    return (a / b - 1) * 100 if b else 0


def detect(bars):
    """Return the patterns visible in this series. Mirrors the app's logic."""
    found = []
    c = [b['c'] for b in bars]
    n = len(c)
    if n < 45:
        return found
    last, prev = c[-1], c[-2]

    # breakout / breakdown: the close crossing the recent range
    look = c[-40:-1]
    hi, lo = max(look), min(look)
    if prev <= hi < last:
        found.append(('Breakout above range', 'bullish', 'fresh',
                      'closed above the 40-day high of %.0f' % hi))
    if prev >= lo > last:
        found.append(('Breakdown below range', 'bearish', 'fresh',
                      'closed below the 40-day low of %.0f' % lo))

    # double top / double bottom from 5-bar pivots
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
        if i2 - i1 < 5:
            continue
        if abs(pct(win[i1], win[i2])) < 3:
            trough = min(win[i1:i2+1])
            if pct(trough, win[i2]) < -3:
                found.append(('Double top', 'bearish', 'possible',
                              'two highs near %.0f with a dip between' % win[i2]))
                break
    for a in range(len(loP) - 1):
        j1, j2 = loP[a], loP[a+1]
        if j2 - j1 < 5:
            continue
        if abs(pct(win[j1], win[j2])) < 3:
            peak = max(win[j1:j2+1])
            if pct(peak, win[j2]) > 3:
                found.append(('Double bottom', 'bullish', 'possible',
                              'two lows near %.0f with a bounce between' % win[j2]))
                break
    # head and shoulders: needs a neckline break, or it is not a signal
    for k in range(len(hiP) - 2):
        i1, i2, i3 = hiP[k], hiP[k+1], hiP[k+2]
        h1, h2, h3 = win[i1], win[i2], win[i3]
        if abs(pct(h1, h3)) < 2.5 and pct(h2, h1) > 4 and pct(h2, h3) > 4:
            neck = max(min(win[i1:i2+1]), min(win[i2:i3+1]))
            if win[m-1] < neck:
                found.append(('Head and shoulders', 'bearish', 'possible',
                              'head %.0f%% above the shoulders, neckline broken'
                              % pct(h2, h1)))
                break
    # inverse head and shoulders
    for k in range(len(loP) - 2):
        j1, j2, j3 = loP[k], loP[k+1], loP[k+2]
        l1, l2, l3 = win[j1], win[j2], win[j3]
        if abs(pct(l1, l3)) < 2.5 and pct(l2, l1) < -4 and pct(l2, l3) < -4:
            neck = min(max(win[j1:j2+1]), max(win[j2:j3+1]))
            if win[m-1] > neck:
                found.append(('Inverse head and shoulders', 'bullish', 'possible',
                              'neckline reclaimed at %.0f' % neck))
                break
    return found


def main():
    uni = universe()
    if not uni:
        print('no universe.json - nothing to scan')
        return 0
    try:
        with open(SEEN) as f:
            seen = json.load(f)
    except Exception:
        seen = {}
    alerts, scanned, failed = [], 0, 0
    for row in uni:
        tk, sym = row.get('tk'), row.get('sym')
        if not tk or not sym:
            continue
        try:
            bars = closes(sym)
            scanned += 1
        except Exception:
            failed += 1
            continue
        for pat, side, conf, note in detect(bars):
            key = '%s|%s' % (tk, pat)
            if seen.get(key):
                continue
            seen[key] = datetime.date.today().isoformat()
            alerts.append({'tk': tk, 'pattern': pat, 'side': side,
                           'confidence': conf, 'note': note,
                           'date': datetime.date.today().isoformat()})
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump({'generated': datetime.datetime.utcnow().isoformat() + 'Z',
                   'scanned': scanned, 'failed': failed,
                   'alerts': alerts}, f, indent=1)
    with open(SEEN, 'w') as f:
        json.dump(seen, f, indent=1)
    os.makedirs(HIST, exist_ok=True)
    with open(os.path.join(HIST, datetime.date.today().isoformat() + '-patterns.json'), 'w') as f:
        json.dump(alerts, f, indent=1)
    print('scanned %d, failed %d, NEW alerts %d' % (scanned, failed, len(alerts)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
