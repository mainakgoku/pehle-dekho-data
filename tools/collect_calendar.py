#!/usr/bin/env python3
"""
Pehle Dekho - forward earnings / corporate action calendar.

The announcements feed only looks BACKWARD (the last 7 days). This looks FORWARD
using NSE's event calendar, which publishes board meetings, results dates, fund
raises and other corporate actions 45 days ahead - with no API key and no mock.

Every row is NSE's own filing. Nothing here is generated.
"""
import json, os, re, sys, time, datetime, urllib.request, http.cookiejar

OUT = os.path.join(os.path.dirname(__file__), '..', 'data', 'calendar.json')
UNI = os.path.join(os.path.dirname(__file__), '..', 'data', 'universe.json')
HDR = {'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
       'Accept': 'application/json, text/plain, */*',
       'Accept-Language': 'en-IN,en;q=0.9',
       'Referer': 'https://www.nseindia.com/companies-listing/corporate-filings-event-calendar'}


def session():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = list(HDR.items())
    try:
        op.open('https://www.nseindia.com/', timeout=20).read()
    except Exception as e:
        print('warm-up failed:', e)
    return op


def kind_of(purpose):
    p = (purpose or '').lower()
    if 'result' in p: return 'results'
    if 'dividend' in p: return 'dividend'
    if 'split' in p or 'bonus' in p: return 'bonus-split'
    if 'fund' in p or 'rights' in p: return 'fundraise'
    if 'agm' in p or 'egm' in p or 'postal' in p: return 'agm-egm'
    return 'board-meeting'


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 45
    today = datetime.date.today()
    to = today + datetime.timedelta(days=days)
    op = session()
    url = ('https://www.nseindia.com/api/event-calendar?index=equities'
           '&from_date=%s&to_date=%s'
           % (today.strftime('%d-%m-%Y'), to.strftime('%d-%m-%Y')))
    rows = []
    try:
        d = json.loads(op.open(url, timeout=30).read().decode('utf-8', 'replace'))
        rows = d if isinstance(d, list) else (d.get('data') or [])
    except Exception as e:
        print('fetch failed:', e)

    tracked = set()
    try:
        u = json.load(open(UNI, encoding='utf-8'))
        for x in u:
            if isinstance(x, dict): tracked.add(str(x.get('tk') or '').upper())
            elif isinstance(x, (list, tuple)) and x: tracked.add(str(x[0]).upper())
    except Exception:
        pass

    out = []
    for r in rows:
        sym = str(r.get('symbol') or '').upper().strip()
        if not sym: continue
        if tracked and sym not in tracked: continue
        ds = str(r.get('date') or '')
        try:
            dt = datetime.datetime.strptime(ds, '%d-%b-%Y').date().isoformat()
        except Exception:
            dt = ''
        out.append({'tk': sym, 'name': str(r.get('company') or '')[:80],
                    'date': dt, 'purpose': str(r.get('purpose') or '')[:80],
                    'kind': kind_of(r.get('purpose')),
                    'note': str(r.get('bm_desc') or '')[:220]})
    out.sort(key=lambda x: (x['date'], x['tk']))
    payload = {'date': today.isoformat(), 'window_days': days, 'source': 'nse-event-calendar',
               'scanned': len(rows), 'events': out[:800],
               'note': 'NSE event calendar, forward-looking. Every row is an exchange filing. Nothing generated.'}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('scanned %d, kept %d forward events' % (len(rows), len(out)))
    for e in out[:6]:
        print('  %-12s %s  %s' % (e['tk'], e['date'], e['purpose'][:40]))


if __name__ == '__main__':
    main()
