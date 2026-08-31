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

// Double, single and template literals. Template literals may span lines; the others may not.
const LITERAL = /"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'|`(?:[^`\\]|\\.)*`/g;
const IGNORE_LINE = /prose-check-ignore/;
const COMMENT_LINE = /^\s*(\/\/|\/\*|\*)/;

function config() {
  const path = join(repoRoot, "prose-check.config.json");
  if (!existsSync(path)) return { include: ["README.md"], exclude: [] };
  return JSON.parse(readFileSync(path, "utf8"));
}

function walk(path, out) {
  const stat = statSync(path);
  if (stat.isDirectory()) {
    for (const entry of readdirSync(path)) {
      if (SKIP_DIR.has(entry)) continue;
      walk(join(path, entry), out);
    }
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
      console.warn(`prose-check: ${entry} does not exist, skipping`);
      continue;
    }
    walk(path, files);
  }
  return [...new Set(files)].filter(
    (f) => !excluded.some((e) => f === e || f.startsWith(e + "/")),
  );
}

// Blank out whole-line comments so a banned phrase quoted in a comment isn't read as copy.
// Line offsets are preserved so reported line numbers still match the real file.
function blankComments(lines) {
  return lines.map((line) => (COMMENT_LINE.test(line) ? "" : line));
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
  const scanned = blankComments(lines).join("\n");
  const index = lineIndexer(scanned);
  const blocks = [];

  for (const match of scanned.matchAll(LITERAL)) {
    const raw = match[0];
    const text = raw
      .slice(1, -1)
      .replace(/\\(.)/g, "$1")
      // A tag ends whatever text preceded it: markup inside a literal (inline SVG,
      // an HTML snippet) holds separate labels, not one long sentence.
      .replace(/<[^>]+>/g, ". ");
    const startLine = index.at(match.index);
    const endLine = index.at(match.index + raw.length - 1);
    if (lines.slice(startLine, endLine + 1).some((l) => IGNORE_LINE.test(l)))
      continue;
    // Skip identifiers, paths, imports and other non-prose strings.
    if (!/\s/.test(text)) continue;
    if (/^[@./]/.test(text)) continue;
    // Coordinate and path data (SVG `d="M12 .5A11.5 ..."`) is not prose.
    const letters = (text.match(/[a-zA-Z]/g) ?? []).length;
    if (letters / text.length < 0.4) continue;
    // Skip CSS blocks written as template literals (styled-jsx, emotion).
    if (/(^|\n)\s*[-a-zA-Z]+\s*:\s*[^;\n{}]+;/.test(text)) continue;

    const tail = scanned
      .slice(match.index + raw.length, index.starts[endLine + 1] ?? scanned.length)
      .replace(/\n$/, "");
    const continues = /^\s*\+\s*$/.test(tail);

    const prev = blocks.at(-1);
    if (prev && prev.continues && startLine === prev.endLine + 1) {
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
  const lines = source.split("\n");
  const kept = [];
  const breaks = new Set();
  let inFence = false;
  let inFrontMatter = lines[0]?.trim() === "---";

  lines.forEach((line, i) => {
    if (inFrontMatter) {
      if (i > 0 && line.trim() === "---") inFrontMatter = false;
      kept.push("");
      return;
    }
    if (/^\s*(```|~~~)/.test(line)) {
      inFence = !inFence;
      kept.push("");
      return;
    }
    if (inFence || IGNORE_LINE.test(line) || /^\s{4,}\S/.test(line)) {
      kept.push("");
      return;
    }
    // A list item or table row is its own idea: start a new block, and drop the
    // cell dividers so a table row isn't read as one long sentence.
    if (/^\s*([-*+]|\d+\.)\s/.test(line)) breaks.add(kept.length);
    if (/^\s*\|/.test(line)) {
      if (/^[\s|:-]+$/.test(line)) {
        kept.push("");
        return;
      }
      breaks.add(kept.length);
      kept.push(line.replace(/\|/g, ". ").replace(/`[^`]*`/g, " "));
      return;
    }
    kept.push(
      line
        .replace(/`[^`]*`/g, " ")
        .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
        .replace(/<[^>]+>/g, " ")
        .replace(/^\s*[#>*\-+]+\s*/, "")
        .replace(/\*\*|__|(?<=\S)\*(?=\S)/g, "")
        .replace(/^\s*\d+\.\s*/, ""),
    );
  });

  return groupLines(kept, breaks);
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

// Copy written directly as JSX text rather than as a string literal. Tags and
// `{expressions}` are dropped; anything still carrying code punctuation is not prose.
function jsxTextParagraphs(source) {
  const kept = blankComments(source.split("\n")).map((line) => {
    const text = line
      .replace(/\{[^{}]*\}/g, " ")
      .replace(/<[^>]*>/g, " ")
      .replace(/&rsquo;|&apos;|&#39;/g, "'")
      .replace(/&[a-z]+;|&#\d+;/g, " ");
    if (/[=;{}()[\]`$<>]/.test(text)) return "";
    // Property signatures and list items in object/type bodies are not prose.
    if (/[,:]\s*$/.test(text)) return "";
    const words = text.trim().split(/\s+/).filter((w) => /[a-zA-Z]/.test(w));
    return words.length < 2 ? "" : text.trim();
  });
  return groupLines(kept);
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
  const kept = blanked.split("\n").map((line, i) => {
    if (IGNORE_LINE.test(line)) return "";
    if (BLOCK_TAG.test(line)) breaks.add(i);
    return line
      .replace(/<!--[\s\S]*?-->/g, " ")
      .replace(/<[^>]*>/g, " ")
      .replace(/&(nbsp|#160);/g, " ")
      .replace(/&(rsquo|apos|#39);/g, "'")
      .replace(/&(mdash|#8212);/g, "\u2014")
      .replace(/&[a-z]+;|&#\d+;/g, " ")
      .trim();
  });
  return groupLines(kept, breaks);
}

function paragraphs(source, file) {
  const ext = extname(file);
  const blocks = MARKDOWN_EXT.has(ext)
    ? markdownParagraphs(source)
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

function sentences(text) {
  // Split after terminal punctuation, allowing closing quotes, brackets and
  // leftover emphasis markers between the period and the space.
  return text
    .split(/(?<=[.!?]["'\u2019\u201d)\]*_]{0,3})\s+/)
    .map((s) => s.trim())
    .filter(Boolean);
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
      const words = sentence.split(/\s+/).length;
      if (words > maxSentenceWords) {
        record(
          lineOfIndex(block, block.text.indexOf(sentence)),
          "error",
          `sentence runs ${words} words (limit ${maxSentenceWords})`,
          sentence,
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
