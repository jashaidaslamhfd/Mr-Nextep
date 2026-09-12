#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.request import Request, urlopen

UA = 'Mr-Nextep-TrendFetcher/1.0'
SOURCES = {
    'google_trends_us': 'https://trends.google.com/trending/rss?geo=US',
    'google_news_us': 'https://news.google.com/rss/search?q=brain+OR+sleep+OR+memory+OR+psychology+OR+stress+OR+behavior&hl=en-US&gl=US&ceid=US:en',
    'nih_news': 'https://news.google.com/rss/search?q=site%3Anih.gov+brain+OR+sleep+OR+memory&hl=en-US&gl=US&ceid=US:en',
}
KEYWORDS = ('brain','sleep','memory','dream','stress','psychology','behavior','emotion','attention','body','neuron','health','science')
NOISE = ('weather','score','odds','game','stock market','lottery','celebrity gossip')

def clean(s): return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', s or ''))).strip()
def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': UA}), timeout=20) as r: return r.read()
def date(s):
    try: return parsedate_to_datetime(s).astimezone(UTC).isoformat()
    except Exception: return ''
def parse(raw, source):
    root=ET.fromstring(raw); out=[]
    for item in root.findall('.//item'):
        # Bind `item` explicitly: a late-binding closure over the loop variable would
        # read whichever element the loop happened to reach last.
        def v(name, element=item):
            n = element.find(name)
            return clean(n.text if n is not None else '')
        title=v('title')
        if title: out.append({'title':title,'url':v('link'),'published_at':date(v('pubDate')),'source':source})
    return out
def score(row):
    t=row['title'].lower(); return sum(k in t for k in KEYWORDS)*3 - sum(k in t for k in NOISE)*6 + (2 if row['source']=='google_trends_us' else 1)
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default='data/search_demand_queue_us.json'); ap.add_argument('--limit',type=int,default=30); a=ap.parse_args()
    rows=[]; errors=[]
    for name,url in SOURCES.items():
        try: rows += parse(fetch(url),name)
        except Exception as e: errors.append(f'{name}: {e}')
    unique={}
    for r in rows:
        r['title']=re.sub(r'\s*[-|–—:].*$','',r['title']).strip()
        key=re.sub(r'[^a-z0-9]','',r['title'].lower())
        if key and key not in unique and score(r)>=3: unique[key]=r
    ranked=sorted(unique.values(),key=score,reverse=True)[:a.limit]
    topics=[]
    for i,r in enumerate(ranked,1):
        # The headline is stored as raw source material only. It used to be turned into a
        # "question_phrase" by lowercasing the first letter and prepending 'Why does ',
        # which is grammatically wrong for any headline carrying its own conjugated verb
        # and produced published titles like "Why does apple acquires brain imaging firm".
        # Writing the title is the model's job now (see content.SYSTEM_PROMPT).
        topics.append({'series_number':f'TREND-{i}','topic':r['title'],'source':r['source'],'source_url':r['url'],'trend_score':score(r),'fetched_at':datetime.now(UTC).isoformat()})
    payload={'source':'Google Trends US + US science RSS','mined_at':datetime.now(UTC).isoformat(),'topics':topics,'source_errors':errors}
    p=Path(a.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps({'output':str(p),'topics':len(topics),'source_errors':errors}))
    return 0 if topics else 2
if __name__=='__main__': raise SystemExit(main())
