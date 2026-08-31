#!/usr/bin/env node
// Flags jargon and LLM-tell phrasing in reader-facing prose.
// Usage: node scripts/prose-check.mjs [file-or-dir...]
// With no arguments it reads prose-check.config.json at the repo root for
// { "include": [...], "exclude": [...] } (paths or directories, relative to the root).
// Handles markdown (.md/.mdx) and string/template literals in .ts/.tsx/.js/.jsx/.mjs.
// Exits 1 if any "error" findings remain. Rules live next to this file in prose-rules.json.

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const rules = JSON.parse(readFileSync(join(here, "prose-rules.json"), "utf8"));

const CODE_EXT = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const MARKDOWN_EXT = new Set([".md", ".mdx"]);
const HTML_EXT = new Set([".html", ".htm"]);
const BLOCK_TAG = /<\s*(p|li|h[1-6]|td|th|tr|div|section|article|blockquote|figcaption|dt|dd)[\s>]/i;
// The same tags, opening or closing, so several elements on one line stay apart.
const BLOCK_TAG_ALL =
  /<\/?\s*(p|li|h[1-6]|td|th|tr|div|section|article|blockquote|figcaption|dt|dd)\b[^>]*>/gi;
// Attributes a reader sees: search results, tooltips, screen readers, empty fields.
const PROSE_ATTR =
  /\b(?:alt|title|aria-label|placeholder)\s*=\s*"([^"]*)"|\b(?:alt|title|aria-label|placeholder)\s*=\s*'([^']*)'/gi;
const META_DESCRIPTION =
  /<meta[^>]*\b(?:name|property)\s*=\s*["'](?:description|og:description|twitter:description)["'][^>]*>/gi;
const CONTENT_ATTR = /\bcontent\s*=\s*"([^"]*)"|\bcontent\s*=\s*'([^']*)'/i;
const HTML_COMMENT = /<!--[\s\S]*?-->/g;
// An inline code span closes on a run of backticks as long as the one that opened it,
// so ``a `b` c`` is one span.
const INLINE_CODE = /(`+)(.*?)\1/g;
// A single CSS value: a length, a custom property, a function call, a colour.
const CSS_TOKEN =
  /^-?[\d.]+(px|rem|em|vh|vw|vmin|vmax|fr|%|s|ms|deg)?,?$|^var\(--[^)]*\),?$|^[a-z-]+\([^)]*\),?$|^#[0-9a-fA-F]{3,8},?$/;
// Attributes whose value is machinery, not copy.
const CODE_ATTR = /\b(className|class|style|href|src|id|key|d|path|url|type|name|role|to|as|from)\s*[=:]\s*\{?$/;
// A period after one of these does not end a sentence, unlike "etc." or "Inc.".
const ABBREVIATION =
  /(?:^|\s)(?:[eE]\.g|[iI]\.e|vs|approx|cf|al|fig|eq|Mr|Mrs|Ms|Dr|Prof|Jr|Sr|U\.S|[A-Z])\.["'\u2019\u201d)\]*_]*$/;
const SKIP_DIR = new Set([
  "node_modules",
  ".git",
  ".next",
  "out",
  "dist",
  "build",
  "coverage",
  "__pycache__",
]);

const IGNORE_LINE = /prose-check-ignore/;

function config() {
  const path = join(repoRoot, "prose-check.config.json");
  if (!existsSync(path)) return { include: ["README.md"], exclude: [] };
  return JSON.parse(readFileSync(path, "utf8"));
}

// A `.json` file is read only when the config names it directly: data directories
// hold fixtures and lockfiles, but a copy deck checked in as JSON is published text.
function walk(path, out, named = false) {
  const stat = statSync(path);
  if (stat.isDirectory()) {
    for (const entry of readdirSync(path)) {
      if (SKIP_DIR.has(entry)) continue;
      walk(join(path, entry), out);
    }
  } else if (named && extname(path) === ".json") {
    out.push(path);
  } else if (
    CODE_EXT.has(extname(path)) ||
    MARKDOWN_EXT.has(extname(path)) ||
    HTML_EXT.has(extname(path))
  ) {
    out.push(path);
  }
  return out;
}

function targets(argv) {
  const { include, exclude = [] } = argv.length
    ? { include: argv }
    : config();
  const excluded = exclude.map((p) => resolve(repoRoot, p));
  const files = [];
  for (const entry of include) {
    const path = resolve(repoRoot, entry);
    if (!existsSync(path)) {
      // A renamed file or a typo would otherwise drop that copy out of CI silently.
      console.error(`prose-check: ${entry} does not exist`);
      process.exitCode = 1;
      continue;
    }
    walk(path, files, true);
  }
  return [...new Set(files)].filter(
    (f) => !excluded.some((e) => f === e || f.startsWith(e + "/")),
  );
}

// Blank out `//` and `/* */` comments so a banned phrase quoted in a comment isn't
// read as copy, without touching comment-looking text inside a string. Comment
// characters become spaces, so every offset and line number still matches the file.
function blankComments(source) {
  const out = source.split("");
  let state = "code"; // code | line | block | " | ' | `
  for (let i = 0; i < source.length; i++) {
    const c = source[i];
    const next = source[i + 1];
    if (state === "code") {
      // `/https?:\/\//` is a pattern, not the start of a comment.
      if (c === "/" && next !== "/" && next !== "*" && startsRegex(source, i)) {
        i = endOfRegex(source, i);
        continue;
      }
      if (c === "/" && next === "/") state = "line";
      else if (c === "/" && next === "*") state = "block";
      else if (c === '"' || c === "'" || c === "`") state = c;
      if (state === "line" || state === "block") {
        out[i] = " ";
        out[i + 1] = " ";
        i++;
      }
      continue;
    }
    if (state === "line") {
      if (c === "\n") state = "code";
      else out[i] = " ";
      continue;
    }
    if (state === "block") {
      if (c === "*" && next === "/") {
        out[i] = " ";
        out[i + 1] = " ";
        i++;
        state = "code";
      } else if (c !== "\n") out[i] = " ";
      continue;
    }
    // Inside a string or template literal.
    if (c === "\\") i++;
    else if (c === state) state = "code";
  }
  return out.join("");
}

// Whether the `/` at `i` opens a regular expression rather than dividing: only an
// operator, an opening bracket or a keyword can precede a pattern.
function startsRegex(source, i) {
  const before = source.slice(0, i).replace(/\s+$/, "");
  if (!before) return true;
  if (/[([{,;:=!&|?+\-*%^~<>]$/.test(before)) return true;
  return /\b(return|typeof|case|in|of|do|else|yield|await|delete|void|instanceof|new)$/.test(
    before,
  );
}

// Offset of the `/` closing the pattern that opens at `i`, skipping escapes and
// character classes. An unterminated pattern gives back the opening slash.
function endOfRegex(source, i) {
  let inClass = false;
  for (let j = i + 1; j < source.length; j++) {
    const c = source[j];
    if (c === "\\") j++;
    else if (c === "\n") return i;
    else if (c === "[") inClass = true;
    else if (c === "]") inClass = false;
    else if (c === "/" && !inClass) return j;
  }
  return i;
}

// A class list (`"flex items-center gap-2 text-sm"`) is styling, not prose.
function looksLikeClassList(text) {
  const tokens = text.trim().split(/\s+/);
  if (tokens.length < 2) return false;
  const classy = tokens.filter((t) =>
    /^-?[a-z0-9]+([-:/.][a-z0-9%.[\]()#-]+)+$/.test(t),
  ).length;
  return classy / tokens.length >= 0.6;
}

// A query, not a sentence. "Create an account" and "With one call ..." open
// ordinary copy, so a leading keyword only counts alongside other SQL syntax.
function looksLikeSql(text) {
  const opens =
    /^\s*(SELECT|INSERT\s+INTO|UPDATE\s+\w|DELETE\s+FROM|WITH\s+\w+\s+AS|CREATE\s+(TABLE|INDEX|VIEW|OR\s+REPLACE)|ALTER\s+TABLE|DROP\s+(TABLE|INDEX|VIEW))\b/i.test(
      text,
    );
  // "where the data comes from" is a sentence, so a couple of ordinary words is
  // not enough: the fragment also needs a construction only SQL writes.
  const sqlOnly =
    /\b(SELECT|GROUP BY|ORDER BY|LEFT JOIN|INNER JOIN|ON CONFLICT|IS NOT NULL|array_agg|COUNT\()/i.test(
      text,
    );
  const keywords = text.match(
    /\b(SELECT|FROM|WHERE|VALUES|SET|GROUP BY|ORDER BY|JOIN|ON CONFLICT|IS NOT NULL|array_agg|COUNT)\b/gi,
  );
  return (opens || sqlOnly) && (keywords?.length ?? 0) >= 2;
}

// A CSS value, not copy. A sentence may mention `64px`, so every word has to be
// part of the value: a length, a function, a colour, or a bare keyword like `solid`.
function looksLikeCssValue(text) {
  const tokens = text.trim().split(/\s+/);
  if (!tokens[0]) return false;
  const cssish = tokens.filter((t) => CSS_TOKEN.test(t)).length;
  if (!cssish) return false;
  return tokens.every((t) => CSS_TOKEN.test(t) || /^[a-z-]+,?$/.test(t));
}

// Decode escapes the way a reader sees them: `\n` is a line break between two
// words, not the letter n joining them.
function unescape(text) {
  return text.replace(/\\(.)/gs, (_, c) => (/[nrtfv0]/.test(c) ? " " : c));
}

// Every string in the source, in source order, including strings written inside a
// template's `${...}`: a conditional there holds copy of its own. A regex cannot
// do this, because a nested template ends the outer one as far as it can tell.
function scanLiterals(source, from = 0, to = source.length, out = []) {
  let i = from;
  while (i < to) {
    const c = source[i];
    if (c === '"' || c === "'") {
      const start = i;
      let text = "";
      i++;
      while (i < to && source[i] !== c && source[i] !== "\n") {
        if (source[i] === "\\") {
          text += source.slice(i, i + 2);
          i += 2;
          continue;
        }
        text += source[i];
        i++;
      }
      if (source[i] === c) {
        out.push({ start, end: i, text });
        i++;
      } else i = start + 1;
      continue;
    }
    if (c === "`") {
      const start = i;
      let text = "";
      i++;
      while (i < to && source[i] !== "`") {
        if (source[i] === "\\") {
          text += source.slice(i, i + 2);
          i += 2;
          continue;
        }
        if (source[i] === "$" && source[i + 1] === "{") {
          const exprStart = i + 2;
          const exprEnd = closingBrace(source, exprStart, to);
          // What the expression prints is not in the source; the strings it holds are.
          scanLiterals(source, exprStart, exprEnd, out);
          text += " ";
          i = exprEnd + 1;
          continue;
        }
        text += source[i];
        i++;
      }
      if (source[i] === "`") {
        out.push({ start, end: i, text });
        i++;
      } else i = start + 1;
      continue;
    }
    i++;
  }
  return out.sort((a, b) => a.start - b.start);
}

// Offset of the `}` closing a substitution, skipping braces and quotes inside it.
function closingBrace(source, from, to) {
  let depth = 1;
  let i = from;
  while (i < to) {
    const c = source[i];
    if (c === "{") depth++;
    else if (c === "}" && !--depth) return i;
    else if (c === '"' || c === "'" || c === "`") {
      const [literal] = scanLiterals(source, i, to);
      if (literal?.start === i) {
        i = literal.end + 1;
        continue;
      }
    }
    i++;
  }
  return to;
}

// A single word can still be a banned word (a `Leverage` button label), but an
// identifier, path, key or class name is not prose.
function isSingleWordProse(text) {
  return /^[A-Za-z][A-Za-z'\u2019]*$/.test(text.trim());
}

// Replace every match with spaces, keeping the newlines so line numbers hold.
function blankRanges(source, re) {
  return source.replace(re, (match) => match.replace(/[^\n]/g, " "));
}

function lineIndexer(text) {
  const starts = [0];
  for (let i = 0; i < text.length; i++) if (text[i] === "\n") starts.push(i + 1);
  return {
    starts,
    at(offset) {
      let lo = 0;
      let hi = starts.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (starts[mid] <= offset) lo = mid;
        else hi = mid - 1;
      }
      return lo; // zero-based
    },
  };
}

// String literals in code, grouped into paragraphs: copy is written as
// `"..." + "..."` across lines, so a paragraph is a run joined by trailing `+`.
function codeParagraphs(source) {
  const lines = source.split("\n");
  const scanned = blankComments(source);
  const index = lineIndexer(scanned);
  const blocks = [];
  // End offset of the literal seen last, whether or not it was kept: a skipped
  // literal between two others breaks the run.
  let prevEnd = -1;
  let prevKept = false;

  for (const literal of scanLiterals(scanned)) {
    const gapJoins =
      prevKept && /^\s*\+\s*$/.test(scanned.slice(prevEnd, literal.start));
    prevEnd = literal.end + 1;
    prevKept = false;
    const text = unescape(literal.text)
      // A tag ends whatever text preceded it: markup inside a literal (inline SVG,
      // an HTML snippet) holds separate labels, not one long sentence.
      .replace(/<[^>]+>/g, ". ");
    const startLine = index.at(literal.start);
    const endLine = index.at(literal.end);
    if (lines.slice(startLine, endLine + 1).some((l) => IGNORE_LINE.test(l)))
      continue;
    // Skip identifiers, paths, imports and other non-prose strings.
    if (!/\s/.test(text) && !isSingleWordProse(text)) continue;
    if (/^[@./]/.test(text)) continue;
    if (looksLikeClassList(text)) continue;
    if (looksLikeCssValue(text)) continue;
    // A value a reader never meets: a class list, a route, a key, an SVG path.
    if (CODE_ATTR.test(scanned.slice(Math.max(0, literal.start - 40), literal.start)))
      continue;
    // Coordinate and path data (SVG `d="M12 .5A11.5 ..."`) is not prose.
    const letters = (text.match(/[a-zA-Z]/g) ?? []).length;
    if (letters / text.length < 0.4) continue;
    // Skip CSS blocks written as template literals (styled-jsx, emotion).
    if (/(^|\n)\s*[-a-zA-Z]+\s*:\s*[^;\n{}]+;/.test(text)) continue;
    // Skip SQL written as a template literal: it is a query, not a sentence.
    if (looksLikeSql(text)) continue;

    const tail = scanned
      .slice(literal.end + 1, index.starts[endLine + 1] ?? scanned.length)
      .replace(/\n$/, "");
    const continues = /^\s*\+\s*$/.test(tail);
    prevKept = true;

    const prev = blocks.at(-1);
    // `"sales " + "motion"` on one line is one phrase, same as across lines.
    if (prev && (gapJoins || (prev.continues && startLine === prev.endLine + 1))) {
      // Preserve the reader-visible spacing: the copy supplies its own spaces.
      const glue = /\s$/.test(prev.text) || /^\s/.test(text) ? "" : " ";
      prev.pieces.push({ start: prev.text.length + glue.length, line: startLine });
      prev.text += glue + text;
      prev.endLine = endLine;
      prev.continues = continues;
    } else {
      blocks.push({
        line: startLine,
        endLine,
        text,
        continues,
        pieces: [{ start: 0, line: startLine }],
      });
    }
  }
  return blocks;
}

// Markdown paragraphs, with code fences, front matter, inline code, link targets
// and HTML tags removed so only prose reaches the rules.
function markdownParagraphs(source) {
  const lines = blankRanges(source, HTML_COMMENT).split("\n");
  const kept = [];
  const breaks = new Set();
  // The open fence marker and its length: a four-backtick fence holds three-backtick
  // examples, so only a run of the same character and at least that long closes it.
  let fence = null;
  // `---` also opens a thematic break. It is front matter only when a closing
  // divider follows and the first line inside reads as a YAML key.
  let inFrontMatter =
    lines[0]?.trim() === "---" &&
    /^[\w-]+\s*:/.test(lines[1] ?? "") &&
    lines.slice(1).some((l) => l.trim() === "---");
  let inList = false;

  lines.forEach((line, i) => {
    if (inFrontMatter) {
      if (i > 0 && line.trim() === "---") inFrontMatter = false;
      kept.push("");
      return;
    }
    const fenceMark = line.match(/^\s*(`{3,}|~{3,})/);
    if (fenceMark) {
      const [char, length] = [fenceMark[1][0], fenceMark[1].length];
      if (!fence) fence = { char, length };
      else if (char === fence.char && length >= fence.length) fence = null;
      kept.push("");
      return;
    }
    if (fence || IGNORE_LINE.test(line)) {
      kept.push("");
      return;
    }
    // Indented text is a code block, unless it continues the list item above it.
    // A blank line does not end a list: its next paragraph may be indented under it.
    if (/^\s{4,}\S/.test(line) && !inList) {
      kept.push("");
      return;
    }
    if (/^\s*([-*+]|\d+\.)\s/.test(line)) inList = true;
    else if (line.trim() && !/^\s{2,}\S/.test(line)) inList = false;
    // A list item, a bold lead-in label or a table row is its own idea: start a
    // new block, and drop the cell dividers so a table row isn't read as one
    // long sentence.
    if (/^\s*([-*+]|\d+\.)\s/.test(line) || /^\s*\*\*/.test(line))
      breaks.add(kept.length);
    // A heading is a title, not the opening clause of the paragraph under it.
    if (/^\s{0,3}#{1,6}\s/.test(line)) {
      breaks.add(kept.length);
      breaks.add(kept.length + 1);
    }
    // A reference definition (`[label]: https://…`) is machinery, never read.
    if (/^\s{0,3}\[[^\]]+\]:\s*\S/.test(line)) {
      kept.push("");
      return;
    }
    if (/^\s*\|/.test(line)) {
      if (/^[\s|:-]+$/.test(line)) {
        kept.push("");
        return;
      }
      breaks.add(kept.length);
      // A cell holds the same markup as any other line, link targets included.
      kept.push(visibleMarkdown(line).replace(/\|/g, ". "));
      return;
    }
    kept.push(
      visibleMarkdown(line)
        .replace(/^\s*[#>*\-+]+\s*/, "")
        .replace(/\*\*|__|(?<=\S)\*(?=\S)/g, "")
        .replace(/^\s*\d+\.\s*/, ""),
    );
  });

  return groupLines(kept, breaks);
}

// What a Markdown line shows a reader: code spans, link targets and tags gone,
// alt text and other attributes of raw HTML pulled to the front.
function visibleMarkdown(line) {
  return (proseAttributes(line) + line)
    .replace(INLINE_CODE, " ")
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    // A reference link shows its text; the label pointing at the definition is
    // invisible, and so is an autolink target.
    .replace(/!?\[([^\]]*)\]\[[^\]]*\]/g, "$1")
    .replace(/<[^>]+>/g, " ");
}

// Consecutive non-empty lines become one paragraph, so a phrase or a sentence
// wrapped across lines is still seen whole.
function groupLines(kept, breaks = new Set()) {
  const blocks = [];
  let current = null;
  kept.forEach((line, i) => {
    if (!line.trim()) {
      current = null;
      return;
    }
    if (breaks.has(i)) current = null;
    if (!current) {
      current = { line: i, endLine: i, text: line.trim(), pieces: [{ start: 0, line: i }] };
      blocks.push(current);
      return;
    }
    current.pieces.push({ start: current.text.length + 1, line: i });
    current.text += " " + line.trim();
    current.endLine = i;
  });
  return blocks;
}

// Copy written directly as JSX text rather than as a string literal. The text
// nodes are pulled out first, so `return <p>copy</p>;` is read as the copy it
// renders rather than thrown away for the `return` and the semicolon around it.
function jsxTextParagraphs(source) {
  const kept = blankComments(source)
    .split("\n")
    .map((line) => {
      const expanded = line
        // An expression is code, but a conditional or a map can hold visible text
        // between tags; keep that and drop the rest.
        .replace(/\{[^{}]*\}/g, (expr) =>
          [...expr.matchAll(/>([^<>{}]+)</g)].map((m) => m[1]).join(". ") || " ",
        );
      // A text node sits after a tag. A line carrying no markup at all continues
      // the text of the line above it.
      const markup = /[<>]/.test(expanded);
      const nodes = markup
        ? [...expanded.matchAll(/>([^<>]*)(?:<|$)/g)].map((m) => m[1])
        : [expanded];
      return nodes
        .map((node) => jsxProse(node, markup))
        .filter(Boolean)
        .join(". ");
    });
  return groupLines(kept);
}

// One JSX text node, kept only if it reads as copy rather than as the code that
// happened to sit between two angle brackets.
function jsxProse(node, betweenTags = true) {
  const text = node
    .replace(/&rsquo;|&apos;|&#39;/g, "'")
    .replace(/&[a-z]+;|&#\d+;/g, " ");
  // Parentheses, semicolons and prices are ordinary punctuation in copy, so a
  // node the tags already delimit keeps them; a line with no markup on it is
  // only a continuation of copy if it carries no statement punctuation either.
  const codeOnly = betweenTags ? /[={}[\]`<>]/ : /[=;{}[\]`$<>]/;
  if (codeOnly.test(text)) return "";
  // A call, an arrow or a boolean operator is code the braces did not enclose,
  // because the expression it belongs to spans several lines.
  if (/\w\(|=>|&&|\|\|/.test(text)) return "";
  // Property signatures and list items in object/type bodies are not prose.
  if (/[,:]\s*$/.test(text)) return "";
  const words = text.trim().split(/\s+/).filter((w) => /[a-zA-Z]/.test(w));
  if (words.length === 1 && isSingleWordProse(words[0])) return text.trim();
  return words.length < 2 ? "" : text.trim();
}

// Copy a reader meets outside the text flow: alt text, tooltips, search results.
function proseAttributes(line) {
  const attrs = [];
  for (const hit of line.matchAll(PROSE_ATTR)) attrs.push(hit[1] ?? hit[2]);
  for (const tag of line.match(META_DESCRIPTION) ?? []) {
    const content = tag.match(CONTENT_ATTR);
    if (content) attrs.push(content[1] ?? content[2]);
  }
  return attrs.filter(Boolean).map((a) => a + ". ").join("");
}

// A tag written across several lines leaves class names, URLs and other machinery
// behind when tags are stripped line by line. Pull it onto its first line, keeping
// the visible attributes and the line count.
function collapseTags(source) {
  return source.replace(/<[a-zA-Z/!][^<>]*>/g, (tag) => {
    if (!tag.includes("\n")) return tag;
    const flat = tag.replace(/\s*\n\s*/g, " ");
    const name = flat.match(/^<\/?\s*([a-zA-Z][\w-]*)/)?.[1] ?? "";
    const marker = BLOCK_TAG.test(`<${name} `) ? `<${name}>` : "";
    return marker + proseAttributes(flat) + "\n".repeat(tag.split("\n").length - 1);
  });
}

// Published HTML pages: script, style and svg bodies dropped, tags removed, and a
// block-level tag starts a new paragraph.
function htmlParagraphs(source) {
  const blanked = source.replace(
    /<(script|style|svg)[\s\S]*?<\/\1\s*>/gi,
    // Keep the line count so reported line numbers stay right.
    (match) => match.replace(/[^\n]/g, " "),
  );
  const breaks = new Set();
  const kept = collapseTags(blankRanges(blanked, HTML_COMMENT)).split("\n").map((line, i) => {
    if (IGNORE_LINE.test(line)) return "";
    if (BLOCK_TAG.test(line)) breaks.add(i);
    return (proseAttributes(line) + line)
      // A block element ends a sentence, so two of them on one line stay apart.
      .replace(BLOCK_TAG_ALL, ". ")
      .replace(/<[^>]*>/g, " ")
      .replace(/&(nbsp|#160);/g, " ")
      .replace(/&(rsquo|apos|#39);/g, "'")
      .replace(/&(mdash|#8212);/g, "\u2014")
      .replace(/&[a-z]+;|&#\d+;/g, " ")
      .trim();
  });
  return groupLines(kept, breaks);
}

// Copy deck checked in as JSON: every string value is read, keys and machinery are
// not. The line is found by matching the value where it is written in the file.
function jsonParagraphs(source) {
  let data;
  try {
    data = JSON.parse(source);
  } catch {
    return [];
  }
  const index = lineIndexer(source);
  const blocks = [];
  let cursor = 0;

  const visit = (value) => {
    if (Array.isArray(value)) return value.forEach(visit);
    if (value && typeof value === "object") return Object.values(value).forEach(visit);
    if (typeof value !== "string") return;
    const encoded = JSON.stringify(value);
    const at = source.indexOf(encoded, cursor);
    if (at >= 0) cursor = at + encoded.length;
    const text = value.replace(/<[^>]+>/g, ". ");
    // The same filters the code scanner uses: an id, a route, a class list or a
    // CSS value is data the reader never meets.
    // A one-word value is a slug, an enum or a key, not a sentence a reader meets.
    if (!/\s/.test(text)) return;
    if (/^[@./#]/.test(text) || /^[a-z]+:\/\//.test(text)) return;
    if (looksLikeClassList(text) || looksLikeCssValue(text) || looksLikeSql(text)) return;
    const line = at >= 0 ? index.at(at) : 0;
    blocks.push({ line, endLine: line, text, pieces: [{ start: 0, line }] });
  };

  visit(data);
  return blocks;
}

function paragraphs(source, file) {
  const ext = extname(file);
  const blocks = MARKDOWN_EXT.has(ext)
    ? markdownParagraphs(source)
    : ext === ".json"
    ? jsonParagraphs(source)
    : HTML_EXT.has(ext)
    ? htmlParagraphs(source)
    : [
        ...codeParagraphs(source),
        ...(ext === ".tsx" || ext === ".jsx" ? jsxTextParagraphs(source) : []),
      ];
  // Report one-based line numbers.
  return blocks.map((b) => ({
    ...b,
    line: b.line + 1,
    pieces: b.pieces.map((p) => ({ ...p, line: p.line + 1 })),
  }));
}

// Sentences with the offset each one starts at, so two identical sentences in one
// paragraph each report their own line. Splits after terminal punctuation, allowing
// closing quotes, brackets and leftover emphasis markers before the space.
function sentences(text) {
  const out = [];
  let offset = 0;
  let pending = null;
  for (const part of text.split(/(?<=[.!?]["'\u2019\u201d)\]*_]{0,3})\s+/)) {
    const trimmed = part.trim();
    const start = offset + (part.length - part.trimStart().length);
    offset += part.length + 1; // rejoining costs one separator
    if (!trimmed) continue;
    // "priced per seat (e.g. $12) and ..." is one sentence, not two.
    if (pending) {
      pending.text += " " + trimmed;
    } else {
      pending = { text: trimmed, start };
      out.push(pending);
    }
    if (!ABBREVIATION.test(pending.text)) pending = null;
  }
  return out;
}

// Which source line a character of the joined paragraph came from.
function lineOfIndex(block, index) {
  let line = block.line;
  for (const piece of block.pieces) {
    if (piece.start <= index) line = piece.line;
    else break;
  }
  return line;
}

export function check(source, rel) {
  const findings = [];
  const record = (line, severity, message, evidence, instead) =>
    findings.push({ file: rel, line, severity, message, evidence, instead });

  const { maxSentenceWords, maxEmDashesPerBlock, maxParenAsidesPerBlock } =
    rules.structure;

  for (const block of paragraphs(source, rel)) {
    // Phrase rules run on the joined paragraph, so line wrapping can't hide a phrase.
    for (const rule of rules.banned) {
      const re = new RegExp(rule.re, rule.caseSensitive ? "g" : "gi");
      for (const hit of block.text.matchAll(re)) {
        record(
          lineOfIndex(block, hit.index),
          rule.severity === "warn" ? "warn" : "error",
          `"${hit[0]}" — ${rule.why}`,
          block.text.slice(Math.max(0, hit.index - 60), hit.index + 100),
          rule.instead,
        );
      }
    }

    for (const sentence of sentences(block.text)) {
      const words = sentence.text.split(/\s+/).length;
      if (words > maxSentenceWords) {
        record(
          lineOfIndex(block, sentence.start),
          "error",
          `sentence runs ${words} words (limit ${maxSentenceWords})`,
          sentence.text,
          "split it; one clause per idea",
        );
      }
    }

    const dashes = (block.text.match(/—/g) ?? []).length;
    if (dashes > maxEmDashesPerBlock) {
      record(
        block.line,
        "warn",
        `${dashes} em dashes in one block (limit ${maxEmDashesPerBlock})`,
        block.text.slice(0, 90) + "…",
        "em-dash pileups are the loudest LLM tell; use periods",
      );
    }

    const parens = (block.text.match(/\(/g) ?? []).length;
    if (parens > maxParenAsidesPerBlock) {
      record(
        block.line,
        "warn",
        `${parens} parenthetical asides in one block (limit ${maxParenAsidesPerBlock})`,
        block.text.slice(0, 90) + "…",
        "promote the important aside to its own sentence, drop the rest",
      );
    }
  }

  return findings;
}

function main() {
  const findings = targets(process.argv.slice(2)).flatMap((file) =>
    check(readFileSync(file, "utf8"), relative(repoRoot, file)),
  );

  const errors = findings.filter((f) => f.severity === "error");
  const warnings = findings.filter((f) => f.severity === "warn");

  for (const f of [...errors, ...warnings]) {
    console.log(`${f.file}:${f.line} [${f.severity}] ${f.message}`);
    console.log(`    context: ${f.evidence.slice(0, 160)}`);
    console.log(`    instead: ${f.instead}`);
  }

  console.log(
    `\n${errors.length} error(s), ${warnings.length} warning(s) across reader-facing prose.`,
  );

  if (errors.length) process.exit(1);
}

// Only run when invoked directly, so the checks can be imported by the tests.
if (
  process.argv[1] &&
  resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))
) {
  main();
}
