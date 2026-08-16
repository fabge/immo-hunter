# Repository guidance

Do not hard-wrap Markdown prose or introduce arbitrary source line breaks. Insert a newline only when an intentional structural or rendered break is desired, such as between paragraphs, headings, list items, block quotes, or code blocks.

Do not preserve backward compatibility unless the requirements or repository explicitly demand it. Choose the simplest implementation that fully meets the current requirements without compromising the intended architecture. Prefer established, well-maintained libraries when they meaningfully reduce implementation or maintenance complexity. Favor durable solutions over temporary workarounds.

## Deferred Fredy evaluation

The repository was evaluated against [Fredy](https://github.com/orangecoding/fredy) on 2026-08-16. Do not integrate Fredy or replace the current stack unless this decision is revisited explicitly.

Fredy is a mature Node.js real-estate application with a web UI, many providers, price/alive tracking, maps, travel-time and financing features, MCP access, and multiple notification adapters. It may add useful coverage through Immowelt, ohne-makler.net, Sparkasse Immobilien, immobilien.de, regionalimmobilien24, Engel & Völkers, McMakler, and NeubauKompass. Its CloakBrowser and residential-proxy strategy may also improve Immowelt coverage, but datacenter IPs can still be blocked.

The current `immo-hunter` stack remains preferable for its small Python/SQLite footprint and personalized automatic LLM ranking for the Heidelberg corridor. Fredy’s MCP support is interactive rather than an equivalent automatic ranking pipeline.

If revisited, first run Fredy as a separate sidecar for roughly two weeks and compare unique relevant listings, Immowelt reliability, latency, bot failures, and false-positive rate against the current collectors. The preferred integration shape is Fredy’s documented HTTP notification adapter feeding an authenticated ingestion endpoint, followed by this repository’s existing deduplication, LLM scoring, and Telegram notification flow.

Do not copy Fredy source code without reviewing its [license](https://github.com/orangecoding/fredy/blob/master/LICENSE): although it includes Apache-2.0 text, it also adds a Commons Clause and attribution/naming restrictions.
