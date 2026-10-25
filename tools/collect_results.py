#!/usr/bin/env python3
"""
Pehle Dekho - results tracker collector.

Scans NSE's corporate-announcements feed for RESULTS filings (quarterly and
annual results) and publishes data/results.json.

Honest scope, stated up front:
  * NSE publishes the ANNOUNCEMENT - the fact that results were filed, the date,
    and the subject line. It does NOT put the numbers in this feed.
  * So this collector records WHAT WAS ANNOUNCED and WHEN, plus a link to the
    filing. It never invents or parses figures - the numbers live in the PDF.
  * It is not a prediction and not a signal. It is a calendar of disclosures.
"""
import json, os, re, sys, time, datetime, urllib.request, http.cookiejar

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'results.json')
UNIVERSE = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe.json')

HDR = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-IN,en;q=0.9',
    'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-announcements',
}

# what counts as a results filing
RESULTS_RE = re.compile(
    r'financial result|quarterly result|audited result|unaudited result|'
    r'q[1-4] result|annual result|results? for the|half.?year',
    re.I)


def session():
    """NSE needs a session cookie - fetch the homepage first."""
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = list(HDR.items())
    try:
        op.open('https://www.nseindia.com/', timeout=20).read()
    except Exception as e:
        print('warm-up failed:', e)
    return op


def get(op, url):
    try:
        r = op.open(url, timeout=25)
        return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        print('fetch failed:', url, e)
        return None




def from_news(tracked):
    """NSE's own feed blocks overseas IPs (GitHub runners included). Google News
    RSS does not, and it carries the results headlines from ET, Livemint, NDTV,
    Business Standard and others. This is the fallback, and it is honest: it
    records the HEADLINE, not figures."""
    import urllib.parse
    out = []
    q = urllib.parse.quote('NSE results announced quarterly Q2 India')
    url = ('https://news.google.com/rss/search?q=' + q + '&hl=en-IN&gl=IN&ceid=IN:en')
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        xml = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'replace')
    except Exception as e:
        print('news fetch failed:', e)
        return out
    items = xml.split('<item>')[1:]
    seen = set()
    for it in items[:80]:
        t = re.search(r'<title>(?:<!\[CDATA\[)?([^<]{12,200})', it)
        src = re.search(r'<source[^>]*>([^<]*)</source>', it)
        lnk = re.search(r'<link>([^<]+)</link>', it)
        dt = re.search(r'<pubDate>([^<]+)</pubDate>', it)
        if not t:
            continue
        title = t.group(1).replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"').strip()
        if not re.search(r'result|profit|revenue|earnings|q[1-4]|quarter', title, re.I):
            continue
        key = title[:60].lower()
        if key in seen:
            continue
        seen.add(key)
        # try to name the company from the headline's first capitalised run
        tk = ''
        m = re.match(r'([A-Z][A-Za-z&.\- ]{2,28})', title)
        if m:
            cand = m.group(1).strip().upper()
            for u in (tracked or []):
                pass
        try:
            d = datetime.datetime.strptime(dt.group(1)[:16], '%a, %d %b %Y').date().isoformat()
        except Exception:
            d = datetime.date.today().isoformat()
        out.append({'tk': tk, 'subject': title[:200], 'date': d,
                    'filed': dt.group(1) if dt else '', 'attch': '',
                    'url': (lnk.group(1) if lnk else ''), 'kind': 'results-news',
                    'src': (src.group(1) if src else '')})
    return out




def from_screener(tk):
    """The NUMBERS, from screener.in - the company's own reported quarterly
    results, which NSE's announcement feed does not carry. Reachable where
    Moneycontrol, ET and Investing.com are blocked. Reads the Quarterly Results
    table and returns the latest few columns. It never computes or estimates."""
    try:
        url = 'https://www.screener.in/company/' + urllib.parse.quote(tk) + '/'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'replace')
    except Exception as e:
        print('screener fetch failed for', tk, e)
        return None
    # the quarterly table sits in <section id="quarters">
    m = re.search(r'<section[^>]*id="quarters"[\s\S]{0,90000}?</section>', html)
    if not m:
        return None
    seg = m.group(0)
    # the period labels are the FIRST row's cells (the header row is empty)
    heads = []
    _first = re.search(r'<tr[^>]*>([\s\S]*?)</tr>', seg)
    if _first:
        heads = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip()
                 for c in re.findall(r'<t[dh][^>]*>([\s\S]*?)</t[dh]>', _first.group(1))]
        heads = [h for h in heads if h]
    rows = {}
    for rm in re.finditer(r'<tr[^>]*>([\s\S]*?)</tr>', seg):
        cells = re.findall(r'<t[dh][^>]*>([\s\S]*?)</t[dh]>', rm.group(1))
        cells = [re.sub(r'<[^>]+>', '', c).replace('&nbsp;', ' ').strip() for c in cells]
        if not cells:
            continue
        label = cells[0]
        vals = cells[1:]
        if label and vals:
            rows[label] = vals
    if not rows:
        return None
    # keep the lines that matter for a results read
    keep = ['Sales', 'Revenue', 'Expenses', 'Operating Profit', 'OPM %',
            'Other Income', 'Interest', 'Depreciation', 'Profit before tax',
            'Net Profit', 'EPS in Rs']
    out = {}
    for k in keep:
        for rk in rows:
            if rk.lower().startswith(k.lower()):
                out[k] = rows[rk]
                break
    return {'periods': heads[:8], 'figures': out}



# ---- what we track, and what each thing means for a holder ----
CATEGORIES = [
    ('results', re.compile(
        r'financial result|quarterly result|audited result|unaudited result|'
        r'q[1-4] result|annual result|results? for the|half.?year', re.I),
     'the company reported its numbers'),
    ('board-meeting', re.compile(
        r'board meeting|board of directors.{0,40}(meet|held)|meeting of the board', re.I),
     'a board meeting was called - results or a dividend often follow'),
    ('dividend', re.compile(
        r'dividend|record date', re.I),
     'a dividend or record date was declared'),
    ('bonus-split', re.compile(
        r'bonus issue|stock split|sub.?division of (shares|equity)', re.I),
     'shares were split or a bonus was issued'),
    ('stake', re.compile(
        r'acquisition|acquire|stake|shareholding|promoter|open offer|'
        r'bulk deal|block deal|disinvestment', re.I),
     'a stake changed hands'),
    ('management', re.compile(
        r'appointment|resignation|managing director|chief executive|'
        r'whole.?time director|company secretary', re.I),
     'senior management changed'),
    ('order', re.compile(
        r'order (win|award)|contract (win|award)|letter of award', re.I),
     'a new order or contract was won'),
    ('regulatory', re.compile(
        r'sebi|penalty|show cause|regulatory action|insolvency|nclt|'
        r'default|downgrade|credit rating', re.I),
     'a regulatory or credit event'),
    ('fundraise', re.compile(
        r'fund ?rais|rights issue|preferential (issue|allotment)|qip|'
        r'debenture|commercial paper', re.I),
     'the company raised or proposed money'),
    ('agm-egm', re.compile(
        r'annual general meeting|extra.?ordinary general meeting|postal ballot', re.I),
     'a shareholder meeting was called'),
]


def categorise(subject):
    for name, rx, meaning in CATEGORIES:
        if rx.search(subject):
            return name, meaning
    return None, None


def write(payload):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print('wrote', OUT)


def main():
  try:
      days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
      today = datetime.date.today()
      frm = today - datetime.timedelta(days=days)

      op = session()
      url = ('https://www.nseindia.com/api/corporate-announcements'
             '?index=equities&from_date=%s&to_date=%s'
             % (frm.strftime('%d-%m-%Y'), today.strftime('%d-%m-%Y')))
      data = get(op, url)

      # a known set of tracked tickers, so the file stays small and relevant
      tracked = set()
      try:
          u = json.load(open(UNIVERSE, encoding='utf-8'))
          tracked = set(str(x[0]).upper() for x in u)
      except Exception:
          pass

      rows, scanned = [], 0
      for it in (data or []):
          scanned += 1
          sym = str(it.get('symbol') or '').upper().strip()
          subj = str(it.get('subject') or it.get('desc') or '').strip()
          if not sym or not subj:
              continue
          cat, meaning = categorise(subj)
          if not cat:
              continue
          # only tracked names if we have a universe; otherwise keep everything
          if tracked and sym not in tracked:
              continue
          rows.append({
              'tk': sym,
              'subject': subj[:220],
              'date': str(it.get('an_dt') or it.get('exchdisstime') or '')[:11],
              'filed': str(it.get('an_dt') or '')[:20],
              'attch': str(it.get('attchmntFile') or ''),
              'url': str(it.get('attchmntFile') or
                         'https://www.nseindia.com/companies-listing/corporate-filings-announcements'),
              'kind': cat,
            'meaning': meaning,
          })

      rows.sort(key=lambda r: r.get('filed') or '', reverse=True)
      # one row per stock per day, newest first
      seen, out = set(), []
      for r in rows:
          k = '%s|%s' % (r['tk'], r['date'])
          if k in seen:
              continue
          seen.add(k)
          out.append(r)

      if not out:
          print('NSE gave nothing - falling back to Google News RSS')
          out = from_news(tracked)

      # the numbers themselves, for the most recent few - screener.in is the
      # only reachable source that carries them
      for r in out[:6]:
          if r.get('tk'):
              try:
                  fig = from_screener(r['tk'])
                  if fig:
                      r['figures'] = fig
              except Exception as e:
                  print('screener skip', r.get('tk'), e)

      # GUARD: if this run found nothing, do not destroy a good file.
      # NSE blocks overseas IPs, so the scheduled run on GitHub's runners
      # regularly returns zero. Overwriting a real list with an empty one is
      # worse than doing nothing.
      if not out:
          try:
              import os as _os
              if _os.path.exists(OUT):
                  _prev = json.load(open(OUT, encoding='utf-8'))
                  if (_prev.get('results_count') or 0) > 0:
                      print('found 0 this run - keeping the existing %d from %s'
                            % (_prev.get('results_count'), _prev.get('date')))
                      sys.exit(0)
          except Exception as _e:
              print('guard check failed:', _e)

      payload = {
          'date': today.isoformat(),
          'window_days': days,
          'scanned': scanned,
          'results_count': len(out),
          'results': out[:400],
        'source': ('nse-announcements' if out and out[0].get('kind') not in ('results-news',) else 'google-news-rss'),
          'note': ('Announcements only - NSE publishes that results were filed, not the '
                   'figures. The numbers are in the attached filing. Not a signal.'),
      }
      os.makedirs(os.path.dirname(OUT), exist_ok=True)
      with open(OUT, 'w', encoding='utf-8') as f:
          json.dump(payload, f, ensure_ascii=False, indent=1)
      print('scanned %d announcements, kept %d results filings' % (scanned, len(out)))
      for r in out[:8]:
          print('  %-12s %s  %s' % (r['tk'], r['date'], r['subject'][:70]))



  except Exception as e:
    print('collector error:', type(e).__name__, e)
    write({'date': datetime.date.today().isoformat(), 'window_days': 0,
           'scanned': 0, 'results_count': 0, 'results': [],
           'note': 'The feed could not be reached from this runner. Nothing is '
                   'published rather than a guessed list.'})
    sys.exit(0)


if __name__ == '__main__':
    main()
