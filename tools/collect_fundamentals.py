#!/usr/bin/env python3
"""
Pehle Dekho - fundamentals collector.

The dossier's technicals refresh every time you open it, but the fundamentals
(P/E, ROE, growth, book value, yield) were baked in at build time and were
weeks old. This collects them from screener.in - the one reachable source that
carries them - and publishes data/fundamentals.json.

Honest scope:
  * screener.in reports what the company filed. This collector copies those
    numbers; it never computes, estimates or infers one.
  * Every record carries the date it was fetched, so the app can show its age.
  * Rate-limited on purpose. 525 companies against one site needs politeness,
    or it blocks and the job publishes nothing.
"""
import json, os, re, sys, time, datetime, urllib.request

OUT   = os.path.join(os.path.dirname(__file__), '..', 'data', 'fundamentals.json')
UNI   = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe.json')
HDR   = {'User-Agent': 'Mozilla/5.0 (Windows NT 11.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/120 Safari/537.36',
         'Accept-Language': 'en-IN,en;q=0.9'}
PAUSE = 6.0          # seconds between companies - screener.in throttles hard (429 after 2)
RETRY = 3            # retries with backoff before giving up on a company

# the labels screener.in prints, mapped to our field names
FIELDS = {
    'Market Cap':        'mcap',
    'Current Price':     'price',
    'High / Low':        'range52',
    'Stock P/E':         'pe',
    'Book Value':        'bookValue',
    'Dividend Yield':    'yield',
    'ROCE':              'roce',
    'ROE':               'roe',
    'Face Value':        'faceValue',
    'Debt / Equity':     'de',
    'OPM':               'opm',
    'EPS':               'eps',
}


def num(v):
    """'1,234.5' -> 1234.5 ; '12.3 %' -> 12.3 ; '--' -> None"""
    if v is None:
        return None
    t = str(v).replace(',', '').replace('%', '').replace('Cr.', '').replace('₹', '').strip()
    m = re.search(r'-?\d+(?:\.\d+)?', t)
    return float(m.group(0)) if m else None


def fetch(tk):
    """One company, with backoff. screener.in answers 429 quickly and then
    blocks for a while, so a failed company is retried slowly rather than
    hammered - and a company that still fails is skipped, not faked."""
    url = 'https://www.screener.in/company/' + urllib.parse.quote(tk) + '/'
    last = None
    for attempt in range(RETRY):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e
            wait = PAUSE * (2 ** attempt)      # 6, 12, 24 seconds
            print('    %s retry %d in %.0fs (%s)' % (tk, attempt + 1, wait, e))
            time.sleep(wait)
    raise last


def parse(html):
    """Pull the top ratios box. screener prints them as
       <li><span class="name">Stock P/E</span><span class="number">25.9</span></li>"""
    out = {}
    # the markup is: <span class="name">Stock P/E</span> ... <span class="number">84.4</span>
    # with a wrapping "nowrap value" span in between, so allow a short gap.
    for m in re.finditer(
            r'<span class="name">\s*([^<]{2,40}?)\s*</span>[\s\S]{0,220}?'
            r'<span class="number">\s*([^<]{1,30}?)\s*</span>',
            html):
        label = re.sub(r'\s+', ' ', m.group(1)).strip()
        val   = m.group(2).strip()
        key   = FIELDS.get(label)
        if key and key not in out:
            out[key] = val
    # growth: screener prints "Compounded Sales Growth" and "Compounded Profit Growth" rows
    for label, key in (('Compounded Sales Growth', 'salesGrowth'),
                       ('Compounded Profit Growth', 'profitGrowth'),
                       ('Stock Price CAGR', 'priceCagr'),
                       ('Return on Equity', 'roeCalc')):
        m = re.search(re.escape(label) + r'[\s\S]{0,600}?<td[^>]*>\s*([\-\d.,]+)\s*%', html)
        if m:
            out[key] = m.group(1) + '%'
    return out


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    tickers = []
    try:
        u = json.load(open(UNI, encoding='utf-8'))
        tickers = [str(x[0]) for x in u][:limit]
    except Exception as e:
        print('universe not found:', e)
        return

    prev = {}
    try:
        prev = json.load(open(OUT, encoding='utf-8')).get('stocks', {})
    except Exception:
        pass

    stocks, ok, failed = {}, 0, 0
    for i, tk in enumerate(tickers):
        try:
            html = fetch(tk)
            row = parse(html)
            if not row:
                failed += 1
                print('  %-12s no ratios found' % tk)
            else:
                row['fetched'] = datetime.date.today().isoformat()
                stocks[tk] = row
                ok += 1
                print('  %-12s P/E %-8s ROE %-6s yield %-5s' %
                      (tk, row.get('pe', '-'), row.get('roe', '-'), row.get('yield', '-')))
        except Exception as e:
            failed += 1
            print('  %-12s failed: %s' % (tk, e))
        time.sleep(PAUSE)

    # keep what we already had for companies this run did not reach
    for k, v in prev.items():
        if k not in stocks:
            stocks[k] = v

    payload = {
        'date': datetime.date.today().isoformat(),
        'source': 'screener.in',
        'requested': len(tickers),
        'ok': ok,
        'failed': failed,
        'stocks': stocks,
        'note': ('Fundamentals as reported by the company, read from screener.in. '
                 'Each record carries the date it was fetched. Nothing is computed '
                 'or estimated. Not a forecast, not advice.'),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print('\ncollected %d of %d (kept %d from the previous run) -> %s'
          % (ok, len(tickers), len(stocks) - ok, OUT))


if __name__ == '__main__':
    import urllib.parse
    main()
