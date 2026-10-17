# Pehle Dekho - pattern alert data

**Data only.** No app source, no keys, no credentials.

An hourly cloud scan detects chart patterns across the tracked NSE universe
and writes only NEW ones to `data/pattern-alerts.json`.

The Pehle Dekho app reads this file to raise pattern alerts.

Detected from daily closes. Short candle patterns are reliable at that length;
head-and-shoulders, double tops and inverse H&S are marked *possible*, never
confirmed. A pattern on its own is not a signal - educational tool, not advice.
