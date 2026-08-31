import assert from "node:assert/strict";
import test from "node:test";

import { check } from "./prose-check.mjs";

const messages = (source) => check(source, "fixture.ts").map((f) => f.message);

test("catches a banned phrase split across concatenated literals", () => {
  const source = [
    "export const copy = {",
    '  body: "Rebuilding was never the sales " +',
    '    "motion, and AI did not change that.",',
    "};",
  ].join("\n");
  assert.ok(messages(source).some((m) => m.includes("sales motion")));
});

test("catches a banned phrase in a template literal", () => {
  const source = "export const copy = { body: `It was the perfect shape for this.` };";
  assert.ok(messages(source).some((m) => m.includes("perfect shape")));
});

test("ignores a banned phrase quoted in a comment", () => {
  const source = [
    "// Readers complained about phrases like \"the opaque majority\" here.",
    "/* also flagged: \"sales motion\" */",
    "export const copy = { body: \"433 companies never published a price.\" };",
  ].join("\n");
  assert.deepEqual(messages(source), []);
});

test("reports the source line a wrapped phrase starts on", () => {
  const source = [
    "export const copy = {",
    '  body: "Nothing wrong on this line at all, plenty of words " +',
    '    "but the moat argument lives down here.",',
    "};",
  ].join("\n");
  const [finding] = check(source, "fixture.ts");
  assert.equal(finding.line, 3);
});

test("flags an over-long sentence assembled from several literals", () => {
  const long = Array.from({ length: 50 }, (_, i) => `word${i}`).join(" ");
  const source = [
    "export const copy = {",
    `  body: "${long} " +`,
    '    "and it keeps going.",',
    "};",
  ].join("\n");
  assert.ok(messages(source).some((m) => m.includes("limit 45")));
});

test("checks markdown prose", () => {
  const source = ["# Heading", "", "Rebuilding was never the moat here.", ""].join("\n");
  const findings = check(source, "fixture.md");
  assert.ok(findings.some((f) => f.message.includes("moat")));
  assert.equal(findings[0].line, 3);
});

test("ignores markdown code fences and inline code", () => {
  const source = [
    "Some clean prose about the 433 companies.",
    "",
    "```js",
    'const label = "the opaque majority";',
    "```",
    "",
    "Inline `sales motion` is a code span, not prose.",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("joins wrapped markdown lines into one paragraph for sentence length", () => {
  const half = Array.from({ length: 30 }, (_, i) => `word${i}`).join(" ");
  const source = [`${half}`, `${half}.`].join("\n");
  assert.ok(check(source, "fixture.md").some((f) => f.message.includes("limit 45")));
});

test("treats each markdown table row and list item as its own block", () => {
  const cell = Array.from({ length: 20 }, (_, i) => `word${i}`).join(" ");
  const source = [
    "| Signal | Why |",
    "|---|---|",
    `| ${cell} | ${cell} |`,
    "",
    `- ${cell}`,
    `- ${cell}`,
  ].join("\n");
  assert.deepEqual(
    check(source, "fixture.md").filter((f) => f.message.includes("limit 45")),
    [],
  );
});

test("leaves clean copy alone", () => {
  const source = 'export const copy = { body: "39 of 47 sites had no pricing link." };';
  assert.deepEqual(check(source, "fixture.ts"), []);
});

test("splits sentences that end inside bold or quotes", () => {
  const source = [
    "**A bolded lead sentence with a fair number of words in it.** Then a second sentence",
    'that says "set up in under five minutes." And a third one that keeps the paragraph going',
    "well past forty-five words in total so a bad splitter would report one long sentence here.",
  ].join("\n");
  assert.deepEqual(
    check(source, "fixture.md").filter((f) => f.message.includes("limit 45")),
    [],
  );
});

test("ignores CSS written as a template literal", () => {
  const source = [
    "const styles = `",
    "  width: 100vw;",
    "  height: 60vh;",
    "  background-image: linear-gradient(to bottom, rgba(0,0,0,0.2), rgba(0,0,0,0.8));",
    "`;",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.tsx"), []);
});

test("strips markup from prose inside template literals", () => {
  const source = [
    "export const body = `",
    '<stat-card icon="MessageSquare" label="Posts Analyzed" value="312"></stat-card>',
    "We read 312 posts.",
    "`;",
  ].join("\n");
  assert.deepEqual(
    check(source, "fixture.tsx").filter((f) => f.message.includes("limit 45")),
    [],
  );
});

test("case-sensitive rules skip lowercase lookalikes such as CSS class names", () => {
  const lower = check('const cls = "cta ghost wide";', "fixture.tsx");
  const upper = check('export const copy = "the demo CTA is above the fold";', "fixture.tsx");
  assert.deepEqual(lower, []);
  assert.ok(upper.some((f) => f.message.includes('"CTA"')));
});

test("checks copy written as JSX text, not only string literals", () => {
  const source = [
    "export default function Page() {",
    "  return (",
    "    <section>",
    "      <p>",
    "        These are prominent, self-promoting market leaders, shown to",
    "        illustrate the landscape.",
    "      </p>",
    "    </section>",
    "  );",
    "}",
  ].join("\n");
  const findings = check(source, "page.tsx");
  assert.ok(findings.some((f) => f.message.includes('"landscape"')));
  assert.deepEqual(findings.filter((f) => f.message.includes("limit 45")), []);
});

test("markup inside a literal separates labels instead of making one long sentence", () => {
  const label = Array.from({ length: 12 }, (_, i) => `word${i}`).join(" ");
  const source = "export const chart = `<svg><title>" + label + "</title><text>" + label + "</text><text>" + label + "</text></svg>`;";
  assert.deepEqual(check(source, "charts.ts").filter((f) => f.message.includes("limit 45")), []);
});

test("ignores coordinate and path data", () => {
  const source = 'export const icon = "M12 .5A11.5 11.5 0 0 0 .5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.37-3.88-1.37-.53-1.34-1.29-1.7-1.29-1.7-1.06-.72.08-.7.08-.7 1.17.08";';
  assert.deepEqual(check(source, "Icons.tsx"), []);
});

test("reads published html pages and skips script bodies", () => {
  const source = [
    "<html><body>",
    "<script>const seamless = 1; // robust",
    "</script>",
    "<h1>How we built it</h1>",
    "<p>",
    "  A seamless, robust pipeline &mdash; really.",
    "</p>",
    "</body></html>",
  ].join("\n");
  const findings = check(source, "page.html");
  assert.ok(findings.some((f) => f.message.includes('"seamless"') && f.line === 6));
  assert.equal(findings.filter((f) => f.line < 4).length, 0);
});

test("skips sql written as a template literal", () => {
  const source = [
    "const rows = await sql`",
    "  SELECT b->>'name' AS name, count(*) AS bids, sum(amount) AS total",
    "  FROM bids WHERE county = ${county} GROUP BY 1 ORDER BY total DESC LIMIT 50",
    "`;",
  ].join("\n");
  assert.deepEqual(check(source, "route.ts"), []);
});

test("a bold lead-in label starts a new block", () => {
  const source = [
    "**Phase 1:** API integration (3-4 days)",
    "**Phase 2:** Permits table and filters (4-5 days)",
    "**Phase 3:** Permit detail page (4-5 days)",
    "**Phase 4:** Search (4-5 days)",
    "**Phase 5:** Interactive map (6-7 days)",
    "**Phase 6:** Analytics dashboard (5-6 days, optional)",
    "**Phase 7:** Polish and optimization (5-7 days)",
  ].join("\n");
  assert.deepEqual(check(source, "README.md"), []);
});

test("ignores trailing and inline comments but not comment-like text in a literal", () => {
  const source = [
    'const a = "Read https://example.com/why-the-moat-matters for more."; // the moat is fine here',
    'const b = /* "landscape" */ "39 of 47 sites had no pricing link.";',
    "/*",
    ' A block comment mentioning the landscape and a seamless, robust pipeline.',
    "*/",
    'const c = "Plain copy about the 433 companies.";',
  ].join("\n");
  assert.deepEqual(
    messages(source).filter((m) => !m.includes('"moat"')),
    [],
  );
  assert.ok(messages(source).some((m) => m.includes('"moat"')));
});

test("joins literals concatenated on one line", () => {
  const source = 'export const copy = "Rebuilding was never the sales " + "motion here.";';
  assert.ok(messages(source).some((m) => m.includes("sales motion")));
});

test("does not join literals that are not concatenated", () => {
  const half = Array.from({ length: 30 }, (_, i) => `word${i}`).join(" ");
  const source = [
    "export const copy = {",
    `  intro: "${half}",`,
    `  outro: "${half}.",`,
    "};",
  ].join("\n");
  assert.deepEqual(
    messages(source).filter((m) => m.includes("limit 45")),
    [],
  );
});

test("checks a one-word label but not a class list", () => {
  assert.ok(messages('const label = "Leverage";').some((m) => m.includes('"Leverage"')));
  assert.deepEqual(messages('const cls = "flex items-center gap-2 text-sm";'), []);
});

test("a longer fence contains shorter fences", () => {
  const source = [
    "````md",
    "```js",
    'const label = "the opaque majority";',
    "```",
    "````",
    "",
    "Clean prose about the 433 companies.",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("inline code spans honour their backtick run", () => {
  const source = "A span ``like `this` seamless one`` stays code, and so does `robust`.";
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("checks prose indented under a list item but not an indented code block", () => {
  const source = [
    "- A list item.",
    "",
    "    The landscape sentence continues the item above.",
    "",
    "Plain paragraph.",
    "",
    "    const label = 'the opaque majority';",
  ].join("\n");
  const findings = check(source, "fixture.md");
  assert.ok(findings.some((f) => f.message.includes('"landscape"')));
  assert.deepEqual(findings.filter((f) => f.message.includes("opaque majority")), []);
});

test("reports each copy of a repeated long sentence on its own line", () => {
  const long = Array.from({ length: 50 }, (_, i) => `word${i}`).join(" ") + ".";
  const source = [long, "", long].join("\n");
  const lines = check(source, "fixture.md")
    .filter((f) => f.message.includes("limit 45"))
    .map((f) => f.line);
  assert.deepEqual(lines, [1, 3]);
});

test("an abbreviation does not end a sentence", () => {
  const words = Array.from({ length: 40 }, (_, i) => `word${i}`).join(" ");
  const source = `A price per seat (e.g. $12) then ${words} and eight more words to pass the limit.`;
  assert.ok(check(source, "fixture.md").some((f) => f.message.includes("limit 45")));
});

test("html block elements on one line stay separate paragraphs", () => {
  const half = Array.from({ length: 30 }, (_, i) => `word${i}`).join(" ");
  const source = `<div><p>${half}.</p><p>${half}.</p></div>`;
  assert.deepEqual(
    check(source, "page.html").filter((f) => f.message.includes("limit 45")),
    [],
  );
});

test("checks html text a reader meets in attributes", () => {
  const source = [
    "<html><head>",
    '<meta name="description" content="A seamless pipeline for 1,074 companies.">',
    "</head><body>",
    '<img src="/chart.png" alt="A robust chart of the 433 companies">',
    '<input placeholder="Search the landscape">',
    "</body></html>",
  ].join("\n");
  const messagesFound = check(source, "page.html").map((f) => f.message);
  assert.ok(messagesFound.some((m) => m.includes('"seamless"')));
  assert.ok(messagesFound.some((m) => m.includes('"robust"')));
  assert.ok(messagesFound.some((m) => m.includes('"landscape"')));
});

test("ignores structural html attributes", () => {
  const source = '<div class="flex items-center"><a href="/moat-and-wedge">Read it</a></div>';
  assert.deepEqual(check(source, "page.html"), []);
});

test("ignores a multiline html comment in markdown and html", () => {
  const source = ["<!--", "A note about the landscape and the moat.", "-->", "", "Clean copy."].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
  assert.deepEqual(check(source, "page.html"), []);
});

test("checks jsx prose containing ordinary punctuation", () => {
  const source = [
    "export default function Page() {",
    "  return (",
    "    <section>",
    "      <p>",
    "        The scan is robust (and it runs offline).",
    "      </p>",
    "    </section>",
    "  );",
    "}",
  ].join("\n");
  assert.ok(check(source, "page.tsx").some((f) => f.message.includes('"robust"')));
});

test("checks jsx text inside a conditional expression", () => {
  const source = [
    "export default function Page({ ready }) {",
    "  return (",
    "    <p>{ready ? <span>A seamless run</span> : <span>Nothing yet</span>}</p>",
    "  );",
    "}",
  ].join("\n");
  assert.ok(check(source, "page.tsx").some((f) => f.message.includes('"seamless"')));
});

test("skips class lists, css values and tagged sql with substitutions", () => {
  const source = [
    "const cls = `px-3 py-1 text-xs font-medium rounded-sm ${active ? 'on' : 'off'}`;",
    "const grid = 'linear-gradient(var(--text-tertiary) 1px, transparent 1px)';",
    "const size = '64px 64px';",
    "await sql`insert into bids (source, external_id) values ('gdot', ${id})`;",
  ].join("\n");
  assert.deepEqual(check(source, "page.tsx"), []);
});

test("skips values of attributes a reader never reads", () => {
  const source = [
    'const a = <a href="/the-moat-and-the-wedge" className="flex items-center">Read it</a>;',
    'const b = <img src="/landscape-of-things.png" alt="A robust chart" />;',
  ].join("\n");
  const found = check(source, "page.tsx").map((f) => f.message);
  assert.deepEqual(found.filter((m) => m.includes('"moat"') || m.includes('"landscape"')), []);
  assert.ok(found.some((m) => m.includes('"robust"')));
});

test("still checks copy that interpolates a value", () => {
  const source = "const msg = `We found ${n} companies with a seamless pricing page.`;";
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("skips a sql fragment without a leading keyword", () => {
  const source = "const q = `array_agg(DISTINCT br.county) FILTER (WHERE br.county IS NOT NULL) AS counties FROM bid_results br`;";
  assert.deepEqual(check(source, "route.ts"), []);
});

test("still reads a sentence that mentions where data comes from", () => {
  const source = 'const note = "This is where the seamless data comes from, and where it goes.";';
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("skips a code line the braces did not enclose", () => {
  const source = [
    "export default function Page() {",
    "  return (",
    "    <div>",
    "      {days",
    "        ? Math.ceil((new Date(bid.deadline).getTime() - Date.now()) / (1000 * 60 * 60 * 24))",
    "        : null}",
    "    </div>",
    "  );",
    "}",
  ].join("\n");
  assert.deepEqual(check(source, "page.tsx"), []);
});

test("reads words separated by an escaped newline", () => {
  const source = 'const copy = "Rebuilding was never the sales\\nmotion for this team.";';
  assert.ok(messages(source).some((m) => m.includes("sales motion")));
});

test("counts a sentence split by escaped whitespace", () => {
  const long = Array.from({ length: 50 }, (_, i) => `word${i}`).join("\\t");
  const source = `const copy = "${long} and it keeps going.";`;
  assert.ok(messages(source).some((m) => m.includes("limit 45")));
});

test("keeps an escaped quote inside copy", () => {
  const source = 'const copy = "She called it \\"seamless\\" in the meeting.";';
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("reads copy in a nested template literal", () => {
  const source =
    "const copy = `${ready ? `a robust path forward` : `a plain path forward`}`;";
  assert.equal(
    messages(source).filter((m) => m.includes('"robust"')).length,
    1,
  );
});

test("reads static copy inside a substitution", () => {
  const source =
    'const copy = `Start here. ${ready ? "a seamless handover" : "a manual handover"}`;';
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("reports the line a nested template sits on", () => {
  const source = [
    "const copy = `",
    "  Nothing wrong on this line, plenty of ordinary words to read.",
    "  ${ready ? `the robust option` : `the other option`}",
    "`;",
  ].join("\n");
  const finding = check(source, "fixture.ts").find((f) =>
    f.message.includes('"robust"'),
  );
  assert.equal(finding.line, 3);
});

test("reads copy in one-line jsx", () => {
  const source = [
    "export function Note() {",
    "  return <p>This is a seamless result for the reader.</p>;",
    "}",
  ].join("\n");
  assert.ok(
    check(source, "note.tsx").some((f) => f.message.includes('"seamless"')),
  );
});

test("reads a one-word label in one-line jsx", () => {
  const source = "const label = <span>Leverage</span>;";
  assert.ok(
    check(source, "note.tsx").some((f) => f.message.includes('"Leverage"')),
  );
});

test("reads one-line jsx from an arrow, a map and an interpolation", () => {
  const arrow = "const Item = () => <p>A robust summary of the work.</p>;";
  const map = "const list = items.map((i) => <li>A robust list entry here.</li>);";
  const interpolated = "const view = <p>A robust view of {count} filings.</p>;";
  for (const source of [arrow, map, interpolated]) {
    assert.ok(
      check(source, "note.tsx").some((f) => f.message.includes('"robust"')),
      source,
    );
  }
});

test("does not read a comparison as jsx text", () => {
  const source = [
    "export function Page() {",
    "  const wide = width > threshold && height < limit;",
    "  return null;",
    "}",
  ].join("\n");
  assert.deepEqual(check(source, "page.tsx"), []);
});

test("reads copy that mentions a measurement", () => {
  const source = 'const copy = "The seamless map tiles are 64px wide on mobile.";';
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("still skips a plain css value", () => {
  const source = [
    'const gap = "12px 24px";',
    'const shadow = "0 1px 2px rgba(0, 0, 0, 0.2)";',
    'const width = "var(--sidebar-width)";',
  ].join("\n");
  assert.deepEqual(messages(source), []);
});

test("reads copy that opens with a sql-shaped word", () => {
  const sources = [
    'const copy = "Create a seamless account in one step.";',
    'const copy = "Update your seamless profile whenever you like.";',
    'const copy = "Delete the seamless draft you no longer need.";',
    'const copy = "With one seamless call you get the whole filing.";',
  ];
  for (const source of sources) {
    assert.ok(messages(source).some((m) => m.includes('"seamless"')), source);
  }
});

test("still skips a real query", () => {
  const source = [
    "const q = `",
    "  SELECT name, robust_score FROM companies",
    "  WHERE robust_score IS NOT NULL",
    "  ORDER BY robust_score DESC",
    "`;",
    'const write = "UPDATE companies SET robust_score = 1 WHERE id = 2";',
  ].join("\n");
  assert.deepEqual(messages(source), []);
});

test("checks prose after a leading thematic break", () => {
  const source = ["---", "", "This is a seamless piece of prose.", ""].join("\n");
  assert.ok(
    check(source, "fixture.md").some((f) => f.message.includes('"seamless"')),
  );
});

test("still skips real front matter", () => {
  const source = [
    "---",
    "title: A seamless title",
    "---",
    "",
    "Ordinary prose about the 433 companies.",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("checks prose under a divider that never closes", () => {
  const source = ["---", "A seamless paragraph with no closing divider."].join("\n");
  assert.ok(
    check(source, "fixture.md").some((f) => f.message.includes('"seamless"')),
  );
});

test("does not join a markdown heading to the paragraph under it", () => {
  const words = Array.from({ length: 40 }, (_, i) => `word${i}`).join(" ");
  const source = [
    "## A fairly long heading with several words in it",
    `${words} and two more.`,
  ].join("\n");
  assert.deepEqual(
    check(source, "fixture.md").filter((f) => f.message.includes("limit 45")),
    [],
  );
});

test("drops a markdown reference definition and label", () => {
  const source = [
    "Read [the filing data][seamless-source] for the numbers.",
    "",
    "[seamless-source]: https://example.com/seamless-robust-data",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("checks alt text in markdown", () => {
  const source = 'Look here: <img src="/a.png" alt="A seamless chart of filings">';
  assert.ok(
    check(source, "fixture.md").some((f) => f.message.includes('"seamless"')),
  );
});

test("checks copy that follows a regular expression", () => {
  const source = [
    "const url = /https?:\\/\\//;",
    'const copy = "A seamless process for the reader.";',
  ].join("\n");
  assert.ok(messages(source).some((m) => m.includes('"seamless"')));
});

test("still ignores a comment after a division", () => {
  const source = [
    "const half = total / 2; // a seamless comment nobody reads",
    'const copy = "433 companies never published a price.";',
  ].join("\n");
  assert.deepEqual(messages(source), []);
});

test("drops an autolink destination in markdown", () => {
  const source = "See <https://example.com/seamless-robust-data> for the numbers.";
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("drops a link target in a markdown table cell", () => {
  const source = [
    "| Source | Link |",
    "| --- | --- |",
    "| Filings | [the data](https://example.com/seamless-robust) |",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.md"), []);
});

test("still reads visible text in a markdown table cell", () => {
  const source = [
    "| Source | Note |",
    "| --- | --- |",
    "| Filings | A seamless handover to the reader |",
  ].join("\n");
  assert.ok(
    check(source, "fixture.md").some((f) => f.message.includes('"seamless"')),
  );
});

test("reads jsx copy that contains a semicolon and a price", () => {
  const source = "const View = () => <p>Filing is seamless; it costs $99 a month.</p>;";
  assert.ok(
    check(source, "fixture.tsx").some((f) => f.message.includes('"seamless"')),
  );
});

test("still ignores a statement on a line with no jsx markup", () => {
  const source = [
    "const total = items.length;",
    "const label = base + suffix;",
  ].join("\n");
  assert.deepEqual(check(source, "fixture.tsx"), []);
});

test("ignores structural attributes in a multiline html tag", () => {
  const source = [
    "<a",
    '  class="robust-card seamless-grid"',
    '  href="https://example.com/comprehensive-landscape"',
    ">Read the filings</a>",
  ].join("\n");
  assert.deepEqual(check(source, "page.html"), []);
});

test("still reads visible attributes in a multiline html tag", () => {
  const source = [
    "<img",
    '  src="/chart.png"',
    '  alt="A seamless chart of the filings"',
    "/>",
  ].join("\n");
  assert.ok(
    check(source, "page.html").some((f) => f.message.includes('"seamless"')),
  );
});
