# Writing prose for humans

Readers of an earlier writeup said it sounded machine-generated: coined metaphors, business
jargon, and sentences that had to be decoded. That applies to anything in this repo a person
reads — README, docs, site copy, blog posts, launch and comment drafts. Not code comments.

1. Run `node scripts/prose-check.mjs` before committing prose. It fails on the banned phrases in
   `scripts/prose-rules.json`, and covers the files listed in `prose-check.config.json`.
   Fix the prose; do not delete the rule.
2. Use the ordinary word. "Selling", not "sales motion". "Use", not "leverage".
   "What stops a competitor", not "moat". "Found", not "surfaced".
3. Never invent a compound term. If a phrase like "page-shaped pain" or "the opaque majority"
   would need a footnote, write the underlying fact instead — usually a number or an action.
4. One idea per sentence, hard limit 45 words. No more than two em dashes and two parentheticals
   per paragraph; both are the loudest tell that a model wrote the text.
5. Every abstraction has to earn its place by carrying a concrete noun with it: who does what,
   priced at what, measured how.
6. A term of art is allowed once if it is defined in the same sentence, in plain words.
7. After drafting, reread every sentence and ask how it would sound spoken aloud to someone
   outside the industry. Anything that fails that test gets rewritten, not softened.
