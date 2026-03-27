# Fubuki Recruiting Intelligence
## Director of Technical Product Management — Ava Labs
## Interview Framework & Org Learning

---

## WHAT THIS IS

This document contains the complete evaluation framework for the Director of Technical Product Management role at Ava Labs, built by a senior engineering manager. Fubuki should internalize this deeply — both as a reference for this specific role and as a template for how to think about future senior technical PM hires.

The framework is exceptional. It reveals exactly how Ava Labs thinks about the PM function, what went wrong with previous hires, and what success looks like. Fubuki uses this to:
- Screen candidates accurately at Stage 1 (recruiter screen)
- Know what to listen for and what to flag for later stages
- Brief candidates appropriately
- Prep hiring managers with the right questions
- Recognize patterns that predict success vs. failure

---

## THE ROLE IN PLAIN ENGLISH

**What it is:** IC-heavy Director building the product management function from scratch. Not a people manager, not inheriting a team. Reports to Martin Eckardt (Sr. Director Developer Relations Engineering). Dotted line to PEG from BizOps — more flexibility than a direct report.

**What it isn't:** Managing an existing PM team. Owning the roadmap. Telling engineers what to build.

**The honest situation:**
- No product function exists
- The roadmap is owned by senior engineers who drive the ACP process
- Multiple previous PMs failed — the engineering team is actively skeptical
- No strong product vision from leadership — they'd be creating one
- High-autonomy, remote-first, engineer-led culture
- Medium-term focus: public permissionless C-Chain

**Why previous PMs failed:** Too much process, too fast. Language of control ("I own the roadmap"). Couldn't earn engineering trust through quality of thinking. Brought frameworks instead of insight. Treated the ACP process as something to sit on top of rather than participate in.

**What success looks like at 90 days:** Engineers want this person in the room. Not "have I shipped a roadmap."

---

## THE 7 EVALUATION DIMENSIONS

### Dimension 1A: Protocol-Level Technical Depth + Product Analysis
**The core test:** Can they read an ACP and layer on the product questions it doesn't ask?

Engineers already have technical depth. The unique value of this PM is reading the same ACP and asking: who benefits? What's the competitive implication? What's the adoption dependency chain? Is this strategically valuable, not just technically correct?

**Reference ACPs for this role:**
- ACP-103: Dynamic Fees
- ACP-176: Dynamic Gas Limits
- ACP-194: Streaming Async Execution
- ACP-209: EIP-7702 Account Abstraction
- ACP-236: Auto-Renewed Staking
- ACP-273: Reduce Min Staking Duration

**Red flag:** Evaluates proposals on technical merit or generic business value without identifying specific beneficiaries, competitive implications, or adoption dependencies.

**Green flag:** Takes a protocol proposal and systematically asks: who benefits, what's the competitive impact, what's the adoption dependency chain. Asks questions engineers haven't considered because they're thinking from the user's perspective.

**Strong green:** Could co-author ACPs. Can perform live product analysis on ACP-194 (Streaming Async Execution) — user-facing value, competitive implications, go-to-market dependencies, risks — without preparation. Can evaluate "early withdrawal of stake with penalty" vs. ACP-273's approach in terms of both technical tradeoffs and institutional requirements (ETF/DAT redemption windows).

---

### Dimension 1B: Problem Framing + Upstream Intervention
**The core test:** Can they catch a misframed problem before it becomes a proposal?

ACP-236 (Auto-Renewed Staking) shipped complexity without adequate product research. Institutions asked for "privacy" when the real question was whether Avalanche's existing primitives could be positioned against Canton. A great product person intervenes upstream — before the engineering investment is in motion.

**Red flag:** Takes problem framing as given. When presented with "institutions want privacy," jumps to evaluating solutions rather than questioning what "privacy" means in context.

**Green flag:** Decomposes requirements — "we need privacy" becomes: confidential from whom, what data, what regulatory framework, what tradeoffs? Spots gaps in proposals by thinking about user workflows the spec doesn't address.

**Strong green:** Track record of catching misframed problems before they became expensive engineering investments. Identifies that the Canton/privacy scenario is a framing and narrative challenge as much as a technical one. Identifies ACP-236 as potentially over-engineered because requirements weren't anchored in user research or competitive benchmarking. Can articulate when the right call is "stop, we're solving the wrong problem" — AND can describe the organizational dynamics of redirecting engineering effort already in motion.

---

### Dimension 2A: Influencing Without Authority
**The core test:** The single strongest predictor of success in this role.

The roadmap is owned by senior engineers. This person cannot succeed through hierarchy or process mandates. They must earn influence by improving the quality of decisions the team is already making.

**Red flag:** Defaults to process-driven approaches. "I own the roadmap." "I set sprint priorities." Shows discomfort when engineers push back on PM involvement. Would be seen as overhead.

**Green flag:** Can describe specific situations where they changed an engineering team's direction through quality of argument, not authority. Comfortable in flat, high-autonomy structures. Knows that product influence in an open community proposal process requires participating credibly in public technical discourse.

**Strong green:** Has a personal playbook for earning trust with skeptical senior engineers. Specific examples of shifting deeply held engineering opinions by bringing market signal, user evidence, or strategic framing that engineers didn't have. Engineers they've worked with would voluntarily seek them out for input — not tolerate them.

---

### Dimension 2B: Product Vision + Organizational Self-Awareness
**The core test:** Can they build a coherent product thesis from fragmented signals — and do they approach it with appropriate humility?

No product vision exists. No function to inherit. They must synthesize direction from users, market data, competitive analysis, and engineering insights. But HOW they approach it matters as much as the thesis, given the history of PM failures.

**Red flag:** Relies on existing roadmaps or leadership direction. Generic answers ("I'd talk to stakeholders"). Arrives with a prescriptive plan ("first month: roadmap; second month: prioritization exercise"). Doesn't acknowledge the org history or the risk of repeating past failures. Has NOT reviewed the ACPs prior to the interview.

**Green flag:** Has experience creating product direction where none existed. Plans to embed with engineering, build relationships, and learn the architecture before proposing changes. Has reviewed the ACPs and references specific proposals.

**Strong green:** Can sketch a preliminary C-Chain product strategy on the spot — target users, critical capabilities, compounding sequence. Has already formed observations from studying the ACPs (e.g., "the recent proposals focus on execution and fee optimization, suggesting a throughput narrative — I'd want to understand how that connects to actual user demand"). Success metric at 90 days is "do engineers want me in the room?" not "have I shipped a roadmap."

---

### Dimension 3A: Competitive Positioning + Strategic Prioritization
**The core test:** Can they connect competitive analysis directly to build decisions, not just describe the landscape?

**Red flag:** Thinks about competition generically ("better UX," "faster transactions"). Prioritizes with abstract frameworks (RICE, weighted matrices) ungrounded in competitive reality. Treats competitive analysis and prioritization as separate activities.

**Green flag:** Connects competitive observations to build implications: "we're behind on staking UX" → "that's why ACP-273 should be prioritized, because the ETF/DAT opportunity has a time window." Understands EVM compatibility as a strategic design parameter, not just a feature flag.

**Strong green:** Articulates which competitive battles are won at the protocol layer vs. ecosystem layer vs. go-to-market layer. Can evaluate the ACP portfolio strategically — e.g., ACP-194 and ACP-176 create a throughput narrative while ACP-204 targets institutional adoption, requiring different sequencing logic. Makes a structured prioritization argument on the spot with compounding rationale.

---

### Dimension 3B: BD-to-Engineering Translation + Stakeholder Navigation
**The core test:** Can they take ambiguous BD-sourced client requests and move them toward engineering-actionable specifications? And do they aggregate patterns rather than treating each request as a one-off?

**Red flag:** Experience limited to one stakeholder type. Treats external requests as a backlog to prioritize rather than signal to interpret. Describes the BD relationship as transactional.

**Green flag:** Has worked with both institutional and crypto-native stakeholders. Can decompose a vague client need into an actionable technical specification. Shows awareness that individual requests often point to systemic gaps.

**Strong green:** Has pushed back on client requests because the systemic solution was different from what was asked for. Has a "Voice of the Builder" instinct — specific example of identifying a recurring pattern across multiple external conversations and advocating for a platform-level solution. Can frame the same protocol change differently for institutional and crypto-native audiences without being intellectually dishonest.

---

### Dimension CC: Communication + Written Clarity
**The core test:** In a remote-first org, written communication is the primary medium for influence. Every interviewer has signal on this.

**Red flag:** Verbose, jargon-heavy, or structurally unclear. Written artifacts show generic frameworks rather than sharp, context-specific thinking.

**Green flag:** Clear, precise, audience-adaptive. Written work shows structured thinking and makes complex tradeoffs legible. Could write a compelling "product rationale" section for an ACP that engineers would respect.

**Strong green:** Exceptionally concise and persuasive. Quality of writing alone would earn credibility with the engineering team. Produces a document during the interview process that makes evaluators think "I wish we had this six months ago."

---

## THE 7-STAGE PROCESS

### Stage 1: Recruiter Screen (30 min — Brian Oh)
**Purpose:** Validate baseline qualifications and logistics before investing senior team time.

**What to cover:**
- Career narrative: what they've done, why this role, why Ava Labs
- Confirm they understand this is IC-heavy, building from scratch, NOT managing a PM team
- Compensation alignment and availability
- Basic domain screen — not depth-testing, just confirming blockchain/infrastructure isn't entirely new
- Logistics: remote setup, timezone feasibility

**What to listen for in Fubuki's recruiter screen:**

| Signal | What to listen for |
|--------|-------------------|
| 2B (light) | Do they describe motivation in terms of opportunity to BUILD, or are they looking for an established function to step into? |
| 2A (light) | When describing past roles, do they naturally reference working WITH engineers or directing engineers? |
| 2B first 90 days | Have they already looked at the ACP repository unprompted? |

**Advance if:** Relevant domain experience (blockchain infrastructure, developer platforms, or protocol-level product work). Clear understanding of IC nature. Logistics work.

**Do not advance if:** No infrastructure/protocol-level experience and no credible path to developing it quickly. Describes the role as "building and managing a PM team."

**Deliverable:** 3-5 sentence written summary: background fit, motivation quality, flags, recommendation. Goes to Martin before Stage 2.

---

### Stage 2: Hiring Manager Screen (45 min — Martin Eckardt)
**Purpose:** Strategic thinking, cultural fit, and whether the candidate has the right instincts for this specific org.

**Structure:**
- First 10 min: Context setting — be CANDID. No product function, engineer-owned roadmap, history of PM failures, EVM compatibility tension, C-Chain focus, no strong product vision from leadership. Also: dotted line to PEG from BizOps = more flexibility. Watch their reaction — do they lean in or stiffen?
- Next 20 min: Strategic conversation (genuine two-way, not structured interview)
- Final 15 min: Candidate questions — quality of questions is strong signal

**The three questions:**

**Q1: "Given what I've described, what's your initial instinct about where a product person adds the most value here?"**
- Red: Generic PM value proposition ("I'd bring the user perspective")
- Good: Identifies the gap between engineer-driven proposals and product/competitive analysis
- Strong: Identifies a non-obvious leverage point — e.g., "The ACP process is actually an asset. The product gap isn't generating ideas, it's evaluating which ideas create competitive advantage and sequencing them."
- Language of control ("own," "drive") = red flag. Language of amplification = strong signal.

**Q2: "How do you think about competitive positioning for an L1 blockchain today? What actually matters?"**
- Red: Feature-level comparison, no framework for why it matters
- Good: Can reason about dimensions of competition and which are decisive vs. table-stakes
- Strong: Recognizes Avalanche's real competition for institutional use cases might be Canton or permissioned chains, not other L1s. Explicitly connects competitive analysis to sequencing.

**Q3: "Tell me about a time you walked into an org that didn't have a product function and built one. What was your first month like? What would you do differently?"**
- Red: Can't name a specific example. First actions were visible artifacts (roadmap, PRD template, stakeholder map).
- Good: First actions were learning-oriented. Relationship with engineering described as collaborative.
- Strong: The story includes a failure and what they learned. "I moved too fast on introducing a prioritization framework and the engineers resisted." First actions were specifically designed to build credibility through contribution. The "do differently" answer reveals a learning directly applicable to this role.

**What candidate questions signal:**

| They ask about | Signal |
|----------------|--------|
| ACP process, recent upgrades, specific technical decisions | Strong — they've done homework |
| Engineering culture, how decisions get made, what happened with previous PMs | Strong — they're diagnosing the org challenge |
| The two VP Engineering roles and where this role sits | Shows org awareness, mapping influence paths |
| Success at 6/12 months | Neutral/low signal |
| Headcount, team size, budget | Mild concern — thinking about this as a management role |
| Product methodology, tooling, process | Moderate concern — process-first orientation |
| Nothing, or only logistics | Do not advance |

**Advance if:** Strategic instinct specific to infrastructure products. Genuine excitement about the ambiguity. Sharp questions. Strongest signal: they say something that makes Martin think about the product challenge differently.

**Do not advance if:** Generic strategic reasoning. Discomfort with lack of existing structure. Past success primarily through process installation. Language of control over engineering.

---

### Stage 3: Technical Deep-Dive (60 min — Stephen Buttolph + Meaghan Fitzgerald)
**Purpose:** Establish whether the candidate can reach the technical depth required to be credible with the engineering team. This is the hardest filter — where previous PM hires would have been caught.

**Structure:**
- First 15 min: Technical foundations, progressively deeper. Finding their ceiling, not confirming a minimum bar.
- Next 15 min: Competitive technical landscape — "How do you think about the technical differences between Avalanche C-Chain, Ethereum L2s, and Solana? Which differences actually matter for adoption?"
- Next 20 min: Walk through a recently activated ACP together (e.g., ACP-176 Dynamic Gas Limits). Tests whether they can engage with ACP-level material in conversation with the engineer who built it.
- Final 10 min: Candidate questions to the engineer.

**Technical topics the engineer explores:**
- EVM execution model: transaction lifecycle, gas metering, state transitions, relationship between execution and consensus
- Fee market design: how EIP-1559 works, dynamic fees, fee burns and tokenomics
- Tokenomics as a system: fee burns (deflationary) vs. staking reward emissions (inflationary), how staking parameters affect validator incentives and token supply dynamics, institutional attractiveness
- Primary Network and P-Chain: UTXO model friction (wallet support, bridging, programmatic interaction), staking mechanics, UX vs. account-based systems like Solana
- L1 architecture: what validators do, how consensus relates to execution, what finality means in practice
- Avalanche-specific (if background exists): P-Chain vs. C-Chain roles, current staking parameter landscape, recent/pending proposals

**Advance if:** The engineer would want this person in the room during technical discussions. They don't need to match the engineer's depth — they need to ask questions that demonstrate real understanding.

**Do not advance if:** Engineer had to simplify repeatedly. Candidate couldn't follow the ACP discussion. Technical reasoning stayed at analogies, not mechanisms. **If there's doubt, do not advance. This is the hardest filter.**

**Engineer's deliverable (3 questions):**
1. Could this person engage credibly in an ACP community discussion?
2. Did they ask any questions that surprised me or that I found genuinely interesting?
3. Would I want them in the room when we're evaluating the next protocol change?

---

### Stage 4: Take-Home + Panel Review (Async 2-3 hrs + 60 min panel — Martin + senior protocol engineer)
**Purpose:** Test written communication, research quality, and depth of product analysis — then stress-test the analysis live.

**The take-home assignment:**
Write a 2-3 page product analysis memo on the assigned ACP (same ACP for all candidates). Must cover:
1. What this proposes and why it matters — in their own words, not a summary of the abstract
2. Who benefits and who bears cost — specific user segments (builders, validators, institutional partners, end users)
3. Competitive implications — how does this change Avalanche's positioning? Differentiation or gap-close?
4. Risks and open questions
5. Recommendation — should the team prioritize this? Under what conditions? What would change their mind?

**Panel structure:**
- First 5 min: Candidate walks through key conclusions in 5 min (tests verbal distillation)
- Next 25 min: Deep-dive and challenge. Engineer challenges technical reasoning. Martin probes product reasoning. Both push on gaps.
- Next 20 min: Extend the analysis — "If you could only pick two major protocol upgrades for the next 6 months, which and why?" / "How would you communicate this to [audience they didn't address]?" / "What's missing from the ACP portfolio? What proposal should exist but doesn't?"
- Final 10 min: Candidate questions

**Advance if:** The memo is something you'd actually circulate internally. The panel showed they can defend, update, and extend under pressure.

**Do not advance if:** Memo reads like a consulting deliverable (polished but generic). Lacks technical engagement. Candidate couldn't adapt reasoning when challenged.

---

### Stage 5: BD Collaboration Round (60 min — Mike Manning + Christopher Kowalski)
**Purpose:** Simulate the actual working relationship with BD. Tests whether the candidate can be an effective product partner to BD — not a repeat of stakeholder navigation, but a live working session.

**Prep materials sent 72 hours before:**
- Topic 1: Blockchain privacy/confidentiality architectures (Canton Network deep-dive specifically)
- Topic 2: Avalanche staking mechanics + ACP-273 + ACP-236 + Solana comparison + ETF/DAT redemption requirements

**Three scenarios (10 min each):**

**Scenario A — Privacy/Confidentiality (Canton angle)**
BD presents: European bank wants fund transfer confidentiality between internal entities. Canton can do this natively. Can Avalanche match it?

What to look for:
- Red: Accepts "we need privacy" at face value or jumps straight to a solution
- Good: Asks clarifying questions (privacy from whom, what data, regulatory framework)
- Strong: Decomposes into layers (transaction confidentiality, data residency, access control, auditability). Identifies Canton's architecture optimizes for a specific model with costs that may or may not apply to this client. Questions whether existing Avalanche primitives, positioned correctly, can meet the actual need. Thinks about what the BD lead can actually SAY to the banking executive.

**Scenario B — AVAX Staking Duration (ETF/DAT)**
BD presents: Two asset managers need 2-day redemption windows but AVAX has 14-day minimum staking. ACP-273 not yet activated. Engineers also discussing early withdrawal with penalty. Clients keep asking when this gets fixed.

What to look for:
- Red: Treats as simple parameter change. Doesn't see the constraint structure.
- Good: Compares ACP-273 vs. early withdrawal with penalty on merits
- Strong: Maps full constraint system (regulatory, technical P-Chain UTXO architecture, economic, product). Recognizes these aren't either/or. Helps BD lead construct a concrete response to asset managers — status of ACP-273, realistic timeline, interim options (partial staking, liquid staking), what commitment BD can make.

**Scenario C — Staking UX / ACP-236 Challenge**
BD presents: Institutions keep citing Solana staking as the gold standard. ACP-236 (auto-renewal) was written to address this but doesn't handle partial withdrawal. Feels like engineering built something without understanding what institutions need.

What to look for:
- Red: Treats ACP-236 as given, suggests incremental improvements
- Good: Acknowledges ACP-236 may have been built on incomplete requirements. Suggests validation first.
- Strong: Directly names the root cause — proposal was written without adequate product research. Doesn't soften it. Frames the right question: "should we continue investing in this approach or step back and define the right requirements first?" This is a preview of exactly how Dimension 2A (influencing without authority) will play out on the job.

**Advance if:** The BD lead would actively want to work with this person. Felt heard, signal valued, thinking improved.

**Do not advance if:** Treated client feedback as either gospel or noise. Couldn't decompose vague requirements. No instinct for challenging problem framing.

**BD deliverable (3 questions):**
1. Would you trust this person to represent your client feedback to engineering accurately and fairly?
2. Did they improve your thinking about any of the scenarios?
3. Would you seek this person out proactively, or would working with them feel like overhead?

---

### Stage 6: (Written Exercise — runs parallel to Stage 5)
**This is the take-home ACP memo.** Sent alongside Stage 5 prep materials after Stage 3. Same document as Stage 4 deliverable.

---

### Stage 7: Final Round — Leadership + Cross-Check (45 min — VP Engineering Platform + Owen Wahlgren, Culture Champion)
**Purpose:** (1) Leadership-level assessment of how they'd operate in the org; (2) Cross-check from the person whose engineering team will be most affected — functions as a practical veto gate.

**Why this VP specifically:** The candidate reports to Martin, but the engineers they most need to influence sit under the VP Engineering Platform (core protocol). If the VP thinks this person won't be effective with their team, the hire fails regardless of other scores.

**Structure:**
- First 20 min: Culture/org fit + values questions (at least 4 from the values framework)
- Next 15 min: Take-home memo review — what the VP agreed with, would challenge, wished the candidate had addressed. Tests whether they can defend analysis under pressure from a senior technical leader.
- Final 10 min: Candidate questions — questions to this VP are particularly revealing.

**Required culture questions:**
1. "Tell me about a time you challenged the status quo and offered a new perspective." (Science fuels innovation)
2. "Describe a situation where you made a mistake. How did you handle it, and what did you learn?" (Act decisively with purpose)
3. "How do you build trust in new teams?" (Foster a community of integrity)
4. "When have you felt most energized at work, and why?" (Drive impact through shared vision)
5. "Our engineers own the roadmap and the ACP process. They're skeptical of PM involvement based on past experience. How would you approach building a working relationship with my team?" (Direct 2A test from the person whose team it is)
6. "What's the difference between a good protocol engineer's judgment about what to build and a good PM's judgment? When do they diverge?" (Tests whether they articulate their value without diminishing engineering judgment)

**Hire if:** The VP Engineering Platform would introduce this person to their team with confidence. "I think this person could earn trust over time and I'd be willing to facilitate that" is sufficient.

**Do not hire if:** VP has concerns this person would create friction. Candidate couldn't articulate their value without implying engineers are currently making bad decisions.

**VP deliverable:**
1. Would you introduce this person to your team with confidence, or with caveats?
2. Based on the written exercise discussion, would this person's analysis actually improve your team's decision-making?

---

## DEBRIEF AND DECISION PROCESS

**Participants:** All interviewers — recruiter, hiring manager, senior protocol engineer, BD lead, VP Engineering Platform.

**Structure:**
1. Independent scoring first — everyone submits before seeing anyone else's scores
2. Round-robin read-out (30 min) — no interruptions during read-outs
3. Dimension-by-dimension discussion (20 min) — focus on disagreements, they usually reveal unresolved role ambiguity
4. Decision (10 min) — hiring manager makes final call

**Hard stops (regardless of other scores):**
- Any "No" on 1A, 1B, or 2A from the relevant primary evaluator → do not hire
- If VP Engineering Platform would not introduce this person to their team with confidence → do not hire
- If BD lead wouldn't seek this person out proactively → serious concern, key value loop will be delayed

**Scoring matrix:**

| Dimension | Recruiter | HM | Engineer | BD Lead | Platform VP |
|-----------|-----------|-----|----------|---------|-------------|
| 1A — Technical depth & product analysis | — | Primary | Primary | — | Secondary |
| 1B — Problem framing & upstream intervention | — | Secondary | — | Primary | — |
| 2A — Influencing without authority | Light | Secondary | — | Secondary | Primary |
| 2B — Product vision & self-awareness | Light | Primary | — | — | Primary |
| 3A — Competitive positioning & prioritization | — | Primary | Primary | Primary | — |
| 3B — BD-to-Eng translation | — | — | — | Primary | — |
| CC — Communication & written clarity | — | Primary | Secondary | Secondary | Secondary |

---

## REFERENCE CHECK GUIDE

**Who to get (4 references, specific relationships):**

| Reference | Why | What they reveal |
|-----------|-----|-----------------|
| Senior engineer who worked closely with them | Most important reference. Directly tests Dimension 2A. | Whether engineers sought them out or tolerated them. Whether they added to technical discussions or were overhead. |
| Engineering leader (VP/Director) | Mirrors the platform VP dynamic | Whether they built credibility across org boundaries. How they navigated disagreements. |
| BD/sales/partnerships counterpart | Mirrors the BD collaboration requirement | Whether they were a useful partner or a bottleneck. Whether they helped BD respond to clients. |
| Direct manager | Standard context | How much direction they needed. Whether they created product direction or executed someone else's. |

**Backdoor references:** If possible, find one engineer who worked with the candidate but WASN'T provided as a reference. The candidate's chosen references are pre-selected for positivity. An unchosen engineer's perspective is often more revealing, especially for Dimension 2A.

If the candidate can't provide a senior engineer reference — that's signal in itself.

---

## WHAT FUBUKI KNOWS TO WATCH FOR AT STAGE 1

### Language patterns that predict failure

| What they say | What it signals |
|---------------|-----------------|
| "I own the roadmap" | Control mindset — will create friction with engineers immediately |
| "I drive product strategy" | Will position themselves above engineering judgment |
| "I'd build a prioritization framework" | Process-first. Likely to repeat the previous PM failure pattern. |
| "I'd align stakeholders" | Generic PM template thinking, not specific to this context |
| "I'd manage the PM team" | Doesn't understand the IC nature of the role |
| "I prefer working at companies with clear product direction" | Will struggle with the ambiguity |

### Language patterns that predict success

| What they say | What it signals |
|---------------|-----------------|
| "I'd need to earn trust before proposing anything" | Self-aware about the trust problem |
| "The ACP process is interesting — I was reading through some of them..." | Has done homework unprompted. Strong signal. |
| "I've worked in orgs where engineering drives the roadmap" | Comfortable with this structure |
| "My value would be bringing signal that engineers don't have time to gather" | Correct framing of the role |
| "I'd focus on asking better questions, not giving better answers" | Influencing without authority instinct |
| "What happened with the previous PMs?" | Diagnosing the org problem — good instinct |

### The ACP litmus test
Before the first call, ask: "Have you had a chance to look at any of Ava Labs' recent ACPs?"
- Looked at multiple ACPs and has specific observations → advance immediately after screening basics
- Looked at one or two → neutral
- Hasn't looked → not a hard stop at Stage 1 but flag it; they need to have looked by Stage 2

---

## ORG LEARNING — WHAT THIS FRAMEWORK TEACHES US

This interview process is one of the most sophisticated Fubuki has seen. Key lessons for future senior technical PM roles:

### 1. The failure mode is almost always "too much process, too fast"
Technical PM hires at engineering-led companies fail when they arrive with a product operating system they want to install. Engineers don't resist product thinking — they resist overhead. The solution is to arrive with curiosity, earn credibility through quality of thinking, and let process emerge from trust rather than precede it.

**Future application:** For any technical PM role at an engineering-led company, weight Dimension 2A (influencing without authority) more than almost anything else. A mediocre technical PM who earns engineering trust will outperform a brilliant one who doesn't.

### 2. Technical depth is a floor, not a ceiling
Previous PM hires failed on technical depth. But depth alone isn't sufficient — engineers already have that. The unique value is the product analysis layer: who benefits, what's the competitive implication, what's the adoption dependency chain. Test for this layering specifically, not just for ability to follow technical specs.

**Future application:** When building interview frameworks for technical PM roles, always test for "product analysis on top of technical understanding" — not just one or the other.

### 3. ACP/RFC/spec engagement is the screening proxy
In any open-source or community-driven technical project, whether the candidate has read the proposals unprompted is the single best Stage 1 filter. It tests initiative, technical interest, and seriousness about the role simultaneously.

**Future application:** For any role at a company with a public technical proposal process (ACPs, EIPs, RFCs, design docs), ask "have you read any of our recent proposals?" in the first call. The answer is highly predictive.

### 4. The BD/engineering translation gap is a systemic problem at technical companies
The pattern described in Stage 5 — BD sources client requirements, no product counterpart to translate them into engineering-actionable specifications, individual requests treated as backlog rather than signal — is nearly universal at technical companies. The "Voice of the Builder" instinct (identifying recurring patterns across external conversations and advocating for platform-level solutions) is rare and extremely valuable.

**Future application:** For technical BD-adjacent roles, always test whether the candidate builds bespoke solutions per client request vs. identifies systemic gaps. Include at least one scenario where the right answer is "what the client asked for isn't what they need."

### 5. Framing the question before evaluating solutions is the most important PM skill nobody screens for
Dimension 1B (problem framing + upstream intervention) is underweighted in most PM interview processes. The ability to catch a misframed problem before it becomes an engineering investment — to say "stop, we're solving the wrong problem" — is enormously valuable and relatively rare. Most candidates jump to solution evaluation.

**Future application:** Include at least one "accept the framing vs. question it" test in every senior PM interview process. Present a vague requirement and watch whether they immediately move to solution space or ask what the requirement actually means.

### 6. The "what would you do differently" question is the best single predictor
In any PM interview where the candidate describes building a function from scratch, "what would you do differently" reveals everything. The best candidates have a specific mistake (usually pacing or scope) whose lesson is directly applicable to this role. The worst candidates say they'd move faster or can't identify anything.

**Future application:** Make this a required question for any "built a function from scratch" story. The self-awareness it reveals predicts organizational effectiveness better than almost anything else.

### 7. Reference checking engineers who WEREN'T provided is underutilized
The backdoor reference — finding an engineer who worked with the candidate but wasn't listed — consistently produces more honest signal on Dimension 2A than provided references. Engineering teams talk. A PM who earns trust leaves a trail; so does one who doesn't.

**Future application:** For senior technical PM hires, always attempt at least one backdoor engineer reference. LinkedIn is usually sufficient to find people who worked at the same company at the same time.

---

## CANDIDATE BRIEFING TEMPLATE (FOR STAGE 1)

When briefing this role to candidates, Fubuki uses this framing:

"This is a Director-level IC role building Ava Labs' product management function from scratch. There's no existing PM team — you're the function. The engineering team drives the roadmap through the ACP process, and the role succeeds by adding competitive, user-facing, and strategic analysis that improves the quality of decisions engineers are already making — not by owning the roadmap or installing a PM process. Previous attempts at this role didn't work out, which means the engineering team is skeptical and trust has to be earned through the quality of your thinking, not through authority or process. The focus is the C-Chain. If that sounds like the kind of challenge you want, it's a genuinely interesting role."

Candidates who light up at that description → advance. Candidates who ask "so who do I report to and when do I start building the PM team?" → do not advance.

---

*Developed from the Ava Labs Director of Technical PM interview framework. Treat as living document — update as the role evolves and as we learn from each hiring cycle.*
