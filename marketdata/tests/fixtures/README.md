# Source-format fixtures

The six CFTC CSV files contain headers and the first two actual rows from annual
2025 archives downloaded from links discovered on the official CFTC historical
archive index on 2026-11-04. Original archive digests and URLs are recorded in
[provenance.json](./provenance.json). Full original archives remain in ignored
local evidence, not in the test fixture set.

[Cboe HTML](./cboe_summary.html) contains the two exact public summary tables
observed for 2026-11-03, with their report heading. Tests verify aggregate volume
and open-interest totals. These are product aggregates, not contract-level bars.

[CME text excerpt](./cme_pg03_excerpt.txt) is a manually transcribed CORN block
from the official public [PG03 PDF](https://www.cmegroup.com/daily_bulletin/current/Section03_Agricultural_Futures.pdf)
observed through the web reader on 2026-11-04. Its headings are reduced to the
required schema terms. It tests the text parser and reconciliation only. It does
NOT certify pypdf extraction or live PDF ingestion. The local downloader could not
retrieve the official CME PDF during this session.

FirstRate sample raw data is private evaluation evidence in the ignored
local evidence directory; it is not redistributed as a repository fixture.

