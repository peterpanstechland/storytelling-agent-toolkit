# Story design: evidence → meaning → experience

Read this when turning raw material into an article, illustrated explanation, social post, narration or a video outline. The same evidence can support different stories; establish the user's intended story before adapting formats.

## Choose a narrative, not a collection of effects

Start with the audience's unanswered question and the change in their understanding by the end. Choose one main structure:

- **Experience → surprise → explanation:** useful for event reporting and a first-person visit. Begin with an observed moment, then explain the mechanism behind it.
- **Problem → attempt → obstacle → result:** useful for Maker projects and hackathons. Show choices and trade-offs; only claim outcomes supported by the project record.
- **Common intuition → evidence → better interpretation:** useful for science and technical explainers. Test the intuition against a concrete example rather than inventing a straw man.
- **Before → intervention → after:** useful for product stories when the two states are comparable. State changed conditions that affect the comparison.
- **One moment → several perspectives:** useful for a sports play, experiment or system incident. Each replay must answer a new question.

Use a beat ledger while editing: `audience question | claim | evidence/asset | explanation | visual action | spoken line | next beat`. An effect earns its place by revealing a relationship, directing attention or changing the viewer's perspective. A repeated transition that answers no new question is a candidate for removal.

## Assume the reader has no preceding chat

Introduce unfamiliar names at first use with their role and relevance. A short opening should establish the situation, who is doing what, and why the audience should care. Explain a technical term at the moment the reader needs it: concrete observation first, technical name second, consequence third.

Weak: “用高斯粒子和虚拟机位呈现。”

Stronger, if the evidence supports it: “换到进攻者身后，原本被身体挡住的协防路线就出现了。这个视角帮助我们分清：谁在追防，谁在堵住篮下。” The production technique belongs in a smaller supporting note if it matters to the audience. Do not claim an inferred view shows an unobserved event accurately.

A term glossary should answer `what it measures/does`, `how to read it here`, and `what it does not establish`. Keep implementation commentary, missing-file notes and “用户提供的图片” out of public copy. Put production status in the handoff report instead. Material limitations that change the meaning of a claim still belong near that claim in plain language.

## Evidence and percentages

Maintain a claim record: `claim ID, exact public wording, source location, event/sample/time scope, transformation, allowed use, verification status`. Link the source to the relevant published claim where the platform permits it. The record can live in a private working directory; it is not an instruction to publish private files.

A percentage needs a named quantity and denominator. Distinguish probability, share, normalized score, rank and percentage-point change. “51%” alone is not an explanation. “模型在相似出手条件下给出的命中概率为 51%” states what the quantity means, provided the source actually says that. It does not describe a personal season average, a guarantee, or a win probability.

For any normalization, record the original scale and formula. A score mapped to 0–100 is not automatically a probability or a share of team attention. Season-level metrics cannot be presented as per-frame measurements. Missing values remain missing: omit the unsupported label, use a neutral state or choose a different supported metric. Never fill a missing player value with a mean and present it as observed.

Do not manufacture comparison figures merely to make a chart look fuller. A hypothetical example is useful only if it teaches a specific concept and is explicitly marked as such beside the number. For a promotional report, prefer fewer well-explained real figures over a mixture of real and hypothetical figures.

## Author, participant and brand identity

Keep separate fields for author/creator, depicted person, quoted speaker, project owner, event organizer and sponsor. Position and adjacency create claims: a close-up of a participant under “我们的作品” can imply that person is the narrator. Use the actual project UI, verified footage of the author, or a clearly contextual event cutaway at that line. A speaker's identity cannot be inferred from clothing or proximity to the author.

Brand display is a project choice. Use the approved supplied logo and wording; do not generalize a past client's logo-only requirement to every future story. Keep authorship visibly separate from event/technology branding so the layout does not imply an official partnership. Track speaker attribution for quotes, permission/allowed use for media, and user-requested exclusions. Avoid silently deleting visually inconvenient but meaningful facts.

## Chinese explanatory and promotional copy

Use concrete verbs and visible consequences: “把三次操作合成一步” is more informative than “赋能高效创新”. Let enthusiasm come from what happened and why it matters. A supported technology benefit can be described confidently without adding uncertainty to every sentence. Avoid unsupported superlatives, invented endorsements and unverified causal claims.

For narration, write in short spoken units with an intentional pause before a reveal. Read it aloud or inspect synthesis for awkward acronyms, numbers and names. Use the user's real pronunciation choices. The on-screen text should usually provide the important noun, contrast or number; it need not duplicate every sentence as a giant title. Accessibility subtitles are a separate track/layer.

For revision, identify the smallest affected beat and its dependent exports. Preserve accepted audio, timing and unrelated scenes unless the requested change requires them. Verify the changed passage in context, not only as an isolated frame.
