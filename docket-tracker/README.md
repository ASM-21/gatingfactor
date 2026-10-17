# docket-tracker (not yet built)

Monitors PA PUC filings for interconnection and tariff keywords, with a
weekly digest.

**Blocked on network egress.** `puc.pa.gov` was unreachable, so the site
structure could not be inspected and writing a scraper against a guessed DOM
would be worse than writing nothing.

## To build it

Keywords per the plan: interconnection, tariff, net metering, DER, PA's
interconnection rulemaking docket, and whichever electric distribution company
you care about (set it in config rather than hardcoding a name, so the tool is
reusable and the repo stays free of a single-utility framing).

Requirements that matter:

- Respect `robots.txt` and rate limit conservatively. This hits a government
  site on a schedule; being a good citizen is not optional.
- SQLite with dedup on docket number plus filing date, so repeated runs only
  add new filings.
- The summarization layer must not fabricate. If a filing's content cannot be
  verified from the source, record the metadata and say the summary is
  unavailable rather than guessing from the title.
- README should note this is for personal awareness only, not for filing
  deadlines or legal reliance.

If the PUC site proves impractical to scrape, fall back to an analogous state
PUC docket system and document why.
