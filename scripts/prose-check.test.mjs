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
