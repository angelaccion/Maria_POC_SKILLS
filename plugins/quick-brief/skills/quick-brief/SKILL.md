---
name: quick-brief
description: Summarize a pasted block of text (notes, an email thread, a transcript excerpt) into a single, tight one-paragraph brief. Use when the user pastes a chunk of raw text and asks for a summary, a brief, or "what's the gist of this".
---

# Quick Brief

Turn the pasted text into exactly one paragraph (4-6 sentences) that a
busy reader could act on without opening the source.

## Rules

1. Lead with the single most important fact or decision in the text,
   not with "this document is about...".
2. Include concrete specifics the source actually states: names,
   numbers, dates, decisions. Never invent any that aren't present.
3. Drop filler, pleasantries, and anything not load-bearing for the
   reader's next action.
4. If the source is ambiguous or missing key context, say so in one
   trailing clause rather than guessing.
5. Output only the paragraph. No heading, no bullet list, no preamble
   like "Here's a summary:".

## Example

Input: a three-paragraph email thread where a vendor proposes a price
increase, a PM pushes back citing a signed rate card, and the vendor
agrees to honor the existing rate through year-end.

Output: "The vendor proposed a price increase that the PM rejected by
citing the signed rate card; the vendor has agreed to honor current
rates through year-end, with the increase presumably back on the table
for renewal. No new rate or renewal date is stated in the thread."
