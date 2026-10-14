# Adapting one story to multiple channels

Read this after the core claims, audience and narrative are clear. Reuse evidence and visual identity while changing pacing and density. Export separate variants rather than forcing one title, crop or caption onto every channel. The platform IDs in [brief-contract.md](brief-contract.md) are stable routing names, not promises of a supported live API.

## Editorial packages

**`wechat-article` — 微信公众号**

A self-contained title, short digest, cover, readable introduction, sectioned article and source/credit notes. For a designed long-image article, prepare deliberate static slices with separate GIFs and a plain-text manuscript. Keep author and sponsor/technology identities distinct. An article's body width and the uploader's image processing should determine final export—not a single universal pixel rule. Preview in the official editor or available authorized connector before release.

**`xiaohongshu` — 小红书图文**

A clear cover promise and a swipe sequence with one question answered per image. The caption should add context, experience and usable details instead of repeating all card text. Each card should still make sense when shared alone: carry a short context marker and any source needed to interpret its number. Use natural, relevant tags; do not manufacture a personal experience or a customer testimonial.

**`csdn` — technical article**

Lead with the practical problem and reproducible outcome. Include the minimal architecture, commands, environment/version assumptions and observed results needed for a reader to follow. Label illustrative pseudocode and unrun commands. Prefer accessible text and code to screenshots of code; use diagrams for relationships. Remove internal credentials, private URLs and proprietary material from examples.

**`aws-builder-center` — AWS Builder Center**

Prepare a technically useful builder story: problem, architecture decisions, implementation, lessons and links to runnable material where available. Keep service claims tied to current official documentation and actual project evidence. A genuine sponsor relationship can be acknowledged without implying endorsement of every implementation claim. Follow the user's brand brief; a Chinese article's naming policy does not automatically apply to another platform. Check the current destination editor and language support when publishing.

**`x` — X**

Make the lead post understandable without opening a thread. A short sequence can progress from question to visual evidence to lesson; each post should contribute something new. Include descriptive image text where supported. Check actual account/upload limits rather than hardcoding universal text length or media counts. Preserve attribution when excerpting the longer article.

## Video packages

**`wechat-channels`, `xiaohongshu-video`, `douyin`** usually benefit from a prompt visual payoff and compact progression. Adapt framing and pacing to the chosen destination and user's brief. Keep important action and captions inside the actual app's safe area. Do not simply crop a horizontal dashboard until labels disappear; recompose data, use a crop that follows the action, or create a portrait insert.

**`bilibili`, `youtube`** can support more deliberate context and explanation. Provide a cover/thumbnail, title, description, subtitle files and credits; use chapter markers when they help navigation. A 2–3 minute explanatory film may need no long fixed brand intro. Establish the question, show proof, explain the mechanism and finish with a memorable consequence. Long-form and short-form variants on the same platform can need different edits.

In every video variant, preserve the evidence's meaning when changing speed, shot order or narration. A real speaker's original excerpt needs accurate attribution and contiguous context. Separate music, original speech and narration when possible for captions, mixing and later edits. A cloned voice requires the relevant person's authorization and appropriate provenance/disclosure for the destination; a synthetic voice is not an authentic recording of a statement.

## What travels together

A publication package should make the intended order and roles unambiguous: copy, cover, ordered media, alternate text, subtitles if applicable, source/credit notes and any platform-specific variants. Keep working-only QA notes separate from the public prose. Record the final local file hashes or version identifiers before handing the package to a publisher, so a later edit does not silently change what was approved.

“Prepare”, “upload to assets”, “save draft”, “schedule” and “publish” are different outcomes. Do only the user-authorized stage. If an authorized connector is unavailable, deliver the complete local package and clear manual steps; never fabricate a successful post URL. Use [publishing.md](publishing.md) for account selection, draft checks, idempotency and result verification.
