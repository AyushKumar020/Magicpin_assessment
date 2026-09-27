# Vera-Beta — magicpin AI Challenge Submission

**Live bot:** https://magicpin-assessment-xebp.onrender.com
**Repo:** https://github.com/AyushKumar020/Magicpin_assessment

## Approach

A FastAPI server (`bot.py`) exposes the 5 required endpoints. Two paths generate messages:

- **`/v1/tick`**: for each `trigger_id`, resolves the merchant/category/trigger contexts
  (including looking up the real digest/offer content a trigger only references by ID —
  e.g. `top_item_id` → the actual research finding text), checks the `suppression_key`
  hasn't been used, and calls `compose()`.
- **`/v1/reply`**: routed through `conversation_handlers.py`. Before any LLM call, cheap
  regex-based detectors (`signals.py`) classify the incoming message as `not_interested`,
  `wait_requested`, `auto_reply_phrase`, or `intent_yes`. This makes the three
  replay-tested behaviors (auto-reply exit, intent transition, hostile/off-topic handling)
  fast and deterministic rather than hoping the LLM classifies correctly every turn —
  and it means a hard "STOP" ends the conversation instantly with zero LLM calls.

Both paths call a single-prompt composer (`composer.py`) against **Groq's
`openai/gpt-oss-120b`** (temperature=0 throughout, for determinism). The composer:
- resolves cross-referenced content (digest items, offers) before prompting, so the model
  never has to guess what a bare ID like `"d_2026W17_jida_fluoride"` refers to
- passes the **original trigger** forward into every reply in a conversation, so a
  multi-turn "yes, send the details" doesn't drift into inventing unrelated content —
  this was a real failure mode we caught in testing (see Tradeoffs)
- trims category/merchant JSON to essentials before sending (cuts token usage ~50-60%,
  important on Groq's free tier: 30 RPM / 8K TPM)
- validates output content, not just JSON validity — catches leaked JSON keys inside
  `body`, banned `**markdown**`, and invalid `cta` enums, with one repair-prompt retry
  before falling back to a safe empty response rather than crashing

## Tradeoffs

- **Free-tier LLM (Groq)**: fast and capable, but 30 RPM/8K TPM on the free tier means
  the bot can occasionally return `{"action": "wait"}` under sustained load rather than
  a composed message. Retry logic is deliberately short server-side (fits within the
  harness's per-call timeout) rather than blocking — batch generation (`submission.jsonl`)
  uses a separate, more patient outer-retry loop since it isn't time-boxed the same way.
- **In-memory state only**: per the testing brief, no persistence layer — state resets on
  restart. Fine for this challenge's scope; a production version would need Redis/Postgres.
- **Anti-hallucination vs. elaboration**: the composer is instructed to ground every claim
  in the given contexts, but for multi-step "send me the details" requests, it does
  reasonably elaborate on real data (e.g. structuring a clinical SOP around a real 3-month
  recall/38% figure) rather than quoting verbatim — this is a judgment call between
  "useful" and "only ever repeats exact source text."
- **Auto-reply detection** uses both a phrase-pattern check (fires on the first canned-reply
  looking message) and an exact-repeat-3x check (per the brief's literal hint) — the
  phrase check triggers one probe, and either a second auto-reply signal or a literal
  repeat ends the conversation gracefully.

## What additional context would have helped

- A **canonical list of canned WhatsApp Business auto-reply phrasings** (ours is
  hand-built from common patterns + Hindi/Hinglish variants) would make detection more
  robust than our regex heuristics.
- **Real send success/delivery telemetry** — right now `/v1/tick` actions are "fire and
  forget" from the bot's perspective; knowing what the harness does after would clarify
  whether more aggressive suppression logic is warranted.
- **Category-specific example messages beyond `Appendix A`** (we only had one worked
  example, for dentists) would have made calibrating tone for gyms/pharmacies/salons/
  restaurants more confident rather than inferred purely from `voice` fields.