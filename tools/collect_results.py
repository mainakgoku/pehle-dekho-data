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
          if not RESULTS_RE.search(subj):
              continue
          # only tracked names if we have a universe; otherwise keep everything
          if tracked and sym not in tracked:
              continue
          rows.append({
              'tk': sym,
              'subject': subj[:220],
              'date': str(it.get('an_dt') or it.get('exchdisstime') or '')[:10],
              'filed': str(it.get('an_dt') or '')[:19],
              'attch': str(it.get('attchmntFile') or ''),
              'url': str(it.get('attchmntFile') or
                         'https://www.nseindia.com/companies-listing/corporate-filings-announcements'),
              'kind': 'results',
          })

      rows.sort(key=lambda r: r.get('filed') or '', reverse=True)
      # one row per stock per day, newest first
      seen, out = set(), []
      for r in rows:
          k = '%s|%s' % (r['tk'], r['date'])
          if k in seen:
              continue
          seen[k] = 1
          out.append(r)

      payload = {
          'date': today.isoformat(),
          'window_days': days,
          'scanned': scanned,
          'results_count': len(out),
          'results': out[:400],
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
