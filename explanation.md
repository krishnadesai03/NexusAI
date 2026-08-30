# What This Project Is (Explained Simply)

This file explains the whole project from scratch, in plain simple language, for someone
who has never seen it before.

## What We Are Building

- An AI helper for a company's employees.
- Employees can ask it questions like "what's our PTO policy" or "how did the team do last sprint."
- One single AI answering everything badly is worse than a few AIs, each really good at one thing.
- So instead of one big AI, we built a **team** of smaller AI helpers, each with its own job.

## Why We Need Several Helpers, Not Just One

- One helper is good at reading company documents (policies, guides).
- Another helper is good at reading work activity (tickets, code changes).
- If we mixed both jobs into one helper, it would get confused about where to look for answers.
- Splitting the work makes each helper simpler and more reliable.

## The Traffic Cop (Orchestrator)

- When a question comes in, something has to decide **which helper** should answer it.
- We built a small AI whose only job is to read the question and pick the right helper.
- If a question needs two helpers at once, it can pick both, and they work at the same time.
- We made sure this "traffic cop" can only ever pick from a fixed list of real helpers — it
  can never invent a helper that doesn't exist. This makes it trustworthy.

## How The Traffic Cop Is Actually Built (No Off-The-Shelf Toolkit)

- There are ready-made "agent framework" toolkits (like LangGraph) that give you a lot of this
  traffic-cop behavior for free. We deliberately didn't use one — everything below was built from
  scratch using plain, ordinary programming building blocks.
- **Picking helpers:** the small AI is asked "which helper(s) should handle this?", but its answer
  is forced into a fixed list — it can never invent a helper that doesn't exist.
- **Running helpers at the same time:** if two helpers are needed, the program starts both at once
  and waits for both to finish — like sending two people to fetch two different things instead of
  sending one, waiting for them to come back, then sending the other. This is one basic, built-in
  programming feature, not a special library.
- **Combining the answers:** whatever each helper found gets bundled together into one response
  handed back to you.
- **Remembering the conversation:** a short list of the last few things you asked and how they were
  answered, kept only in the running program's memory — nothing fancy, and it disappears the moment
  the program stops.
- **Pausing before risky actions:** the one helper that can actually send something just remembers
  "here's a draft I haven't sent yet" as a simple note. Nothing goes out until you click Send —
  there's no special "pause the whole program" machinery behind it.
- **Watching it work live:** as the traffic cop and helpers work, they each announce small updates
  ("I picked these helpers," "this one just finished," "this one is now looking something up"). The
  web page listens for these announcements and updates your screen as they happen, instead of just
  showing a spinner until everything is done.
- **The core idea:** every "smart" behavior a ready-made toolkit would hand you for free — running
  things at once, remembering context, pausing for approval, showing live progress — was built here
  with plain, ordinary code instead. It's more work to build, but there's no hidden machinery:
  everything it does, there's an exact, readable piece of code that does it.

## Helper #1: The Document Reader (Knowledge Agent)

- This helper answers questions using real company documents — like PTO policy, expense
  policy, onboarding guides.
- To find the right document, it turns the question and every document into "meaning
  numbers" — similar meanings get similar numbers.
- It compares the question's numbers to every document's numbers and picks the closest ones.
- It only answers using what it actually found in the documents — never from memory or guessing.
- If nothing relevant is found, it honestly says "I don't know" instead of making something up.

## Problems We Found With The Document Reader

- At first, it was too strict about what counted as "close enough" — it threw away a
  document that was actually the correct answer, just because the match wasn't perfect.
  We fixed it by trusting the AI's final judgment more than a strict number cutoff.
- A short document covering five different topics confused it, because the important detail
  got buried among unrelated details. We fixed it by splitting long documents into smaller,
  focused pieces before storing them.
- It once picked the wrong answer between two very similar-sounding documents (a general
  rule vs. a more specific rule). We fixed it by telling the AI to look for and prefer the
  more specific rule.

## Evaluation of Knowledge Agent steps

- First try: a bigger split size. Problem: it worked fine on most documents, but on one document
  it accidentally cut a numbered how-to step in half, splitting one instruction across two pieces.
- We shrank the split size until that stopped happening, then re-ran every real test question
  through it again. Every one of them matched its document better than before, and the
  numbered-step document was no longer getting cut mid-instruction.
- Other fancier splitting strategies (semantic, structure-aware, sentence) — we skipped those on purpose because our documents are short and simple. They can be used in future when documents get much longer or more complex (long manuals with sections, legal-styletext, etc.)
- The embedding model was picked mainly because it's cheap and we're already using the
  same AI provider everywhere else — not picked by comparing it against other options. We checked
  it was actually good enough by looking at real scores in the retrieval quality eval step.
- Retrieval Quality Eval checks: "did the correct document show up in the top results at all: Recall" and "how close to the very top did it rank: MRR" Results: correct document was the #1 result 7 out of 8 times (88%), and was in the top 3 results 8 out of 8 times (100%); on average it ranked very close to the top (a score of 0.938 out of a possible 1.0).
- Why not precision & nDCG — they're built for questions with *several* correct documents of *different* degrees of correctness. Our questions each have exactly one single correct document, so those two checks wouldn't tell us anything the two we already used don't.
- For the final step — output generated by LLM — we used 2 different methods: A. Deterministic test (whether llm found an answer or said "I don't know", and if yes, whether correct documents were citated) and B. LLM as a judge to check "Faithfulness" (everything cited and nothing made up) and "Answer Relevancy". All 8 gradeable questions passed both checks.

## Helper #2: The Work Activity Reader (Performance Agent)

- This helper answers questions about team performance — finished tickets, sprint progress,
  code commits.
- Since there's no real company behind this project, we built a **pretend company** with
  fake — but realistic — employees, tickets, and code history.
- This helper connects to real tools companies actually use: Jira (tickets), Confluence
  (notes), and Bitbucket (code).

## Building a Pretend Company To Test With

- We invented a fake company with 4 fake employees, each with a real role (backend,
  frontend, tester).
- We created 6 months of realistic history: sprints, tickets, code commits, and notes —
  all fake, but shaped like real work.
- We even planned two employees each having one unusually quiet stretch, with a written
  note explaining why (like being on leave), so the helper could learn to notice patterns
  and explain them, not just count numbers.

## Problems We Found While Building The Pretend Company

- One tool's login worked completely differently from another tool's login, even though
  both belonged to the same company account. We had to test different login styles until
  we found what actually worked for each one.
- Marking a ticket "done" didn't always properly mark it as finished — sometimes it silently
  failed. We fixed it by double-checking and correcting it directly.
- We accidentally tried to create the same note twice and it got rejected. We fixed it by
  checking first whether something already exists before creating it again.
- One tool's free plan had a limit on how many people could be added, and we hit that limit
  by accident, which blocked us from saving new data. Removing the extra people fixed it.
- A very old, no-longer-supported way of searching stopped working overnight because the
  company that owns the tool shut it down. We had to switch to their newer replacement.

## How The Work Activity Reader Actually Answers Questions

- Some questions need more than one lookup — like "compare two people's performance."
- So this helper doesn't just answer in one shot. It can look something up, think about
  what it found, look up something else if needed, and only then answer.
- Every time it looks something up, we keep a private record of exactly what it checked —
  so its answers can always be double-checked against real data.

## The Locked Door We Ran Into

- There's a "proper," modern way for AI helpers to connect directly to tools like Jira and
  Bitbucket. We tried building it that way first.
- After a lot of testing, we hit a wall: the tool provider requires special extra access we
  don't currently have, and there was nothing more we could configure on our side to fix it.
- Rather than get stuck waiting, we switched to a simpler, already-proven way of connecting
  that works today. We wrote down exactly what we tried, so it's easy to switch back later
  if that special access ever becomes available.

## Helper #3: The Database Reader (Database Agent)

- This helper answers questions about company data stored in tables — employees, customers,
  sales deals, expenses, budgets, support tickets.
- Instead of searching documents, it writes a real database query on the fly to get exactly
  the numbers it needs.
- It can only ever look at data. It has no way to change, add, or delete anything — by design,
  not by asking it nicely not to.

## How We Made Sure It Can Never Change Data

Three real guardrails stack on top of each other before any query actually runs — plus one more
thing that isn't a guardrail itself, but is what makes the other three work.

- **Level 1 — the agent's own intelligence.** In plain English, we tell it to only read data.
  Most of the time it simply listens and never even tries to write anything — this is a
  judgment call the AI makes, not something enforced.
- **Level 2 — our own code checking the query text.** Before any query it writes gets sent to
  the database, our code reads the text and looks for change-related words through RegEx (like
  delete, update, create). If it finds one, it refuses to send the query at all. This one is
  deterministic, not a judgment call — plain code, always the same result for the same input.
- **Level 3 — the database's own login permissions.** Even if both checks above somehow failed,
  the query reaches the database using a login that was only ever given permission to read,
  never to write. The database itself refuses any change — this isn't our code deciding
  anymore, it's the database enforcing its own rules. This is the one that actually matters
  most: it can't be tricked or reasoned around, because it isn't app logic at all.

**The thing that isn't a guardrail, but makes the others work:** we only ever built one action
for the AI to call — "run a query." We never built a "delete this row" or "change that" action.
This doesn't stop anything by itself — if the AI decided to try a delete, it would just type
`DELETE` into that same one action's query text, and that text really does get sent there. What
this single-action design actually buys us is simpler: it guarantees every attempt, read or
write, has to pass through the exact same door. That's precisely why Level 2's text check is
enough to catch everything — there's no second door it could have gone through instead.

## Swapping a Smart Check for a Simple One

- We first considered adding a second AI call, just to double-check whether a query looked
  safe before running it.
- We realized that doesn't actually add safety — an AI's judgment can still be wrong or
  fooled, while the database's own permission check (Level 3 above) can't be.
- So instead we used a plain, fixed set of rules that scans the query's text for
  change-related words — the same real protection, but instant, free, and nothing left to guessing.

## Evaluation of DB Agent steps

- We tested the AI's ability to write genuinely complex SQL, not just simple lookups — questions
  requiring multiple combined filters, joining multiple tables, date math, a subquery, and a
  CTE. The test set also includes several
  tricky non-read (write) attempts wrapped in that same complexity.
- We also measured how well the safety guardrails perform using a confusion matrix (correctly
  blocked vs. wrongly blocked vs. correctly allowed vs. wrongly allowed):

  | | Predicted: Blocked | Predicted: Allowed |
  |---|---|---|
  | **Actually unsafe** | 12 (correctly blocked) | 0 (slipped through) |
  | **Actually safe** | 0 (wrongly refused) | 15 (correctly allowed) |

## Helper #4: The Messenger (Communication Agent)

- This helper can actually send a real Slack message or a real email on your behalf.
- Every helper before this one only ever *answered questions* — the worst thing it could do
  was give a wrong answer. This one can *do something real*, which is a different, bigger risk:
  a wrong destination isn't harmless the way a wrong answer is.
- So the guardrail here is different in kind, not just degree: **the AI is never allowed to
  choose where a message goes at all.** Slack always goes to one fixed, pre-approved channel.
  Email always goes to one fixed, pre-approved address — with one narrow exception below. The
  AI only ever controls *what the message says*, never *who receives it*.
- We deliberately did not add a "please confirm before sending" step yet. Since the destination
  is already locked down to safe test targets, an unconfirmed send can only ever reach us —
  so a confirmation step would add complexity without adding real safety, for now.

## Letting It Reach Specific (Safe) People By Name

- We wanted to be able to say "email Priya Nair" and have it actually reach her test inbox,
  not just a single generic default address.
- The fix keeps the same safety idea intact: the AI can only supply a short name tag (like
  "priyanair"), never a real address. Our own code — not the AI — turns that tag into an actual
  address, by attaching it to the *same* real, already-approved mailbox this agent sends from.
- That means every address it could ever possibly construct is still a variant of the one real
  inbox we already trust — never a genuinely different person's real address.
- If asked to email someone who isn't one of the four known test people, it correctly says it
  can't, instead of guessing a name tag that might land somewhere unintended.

## Giving It Memory

- Until now, every single question was answered as if it were the very first thing ever asked
  — nothing about earlier questions in the same conversation was remembered at all.
- That meant an obvious follow-up like "what about Marcus Chen?" (right after asking about
  someone else's salary) had no way to know what you actually meant.
- The fix: the traffic cop now keeps a short running record of the last 5 exchanges — who asked
  what, and which helper answered with what — and hands that record to whichever helper(s)
  answer the current question.
- This record only lives for as long as the program keeps running. Close it, and it's gone —
  it doesn't get saved anywhere permanent yet.
- It had to live with the traffic cop, not inside any one helper, because a follow-up question
  can easily get sent to a completely different helper than the one before it — if each helper
  only remembered its own past, that continuity would break the moment routing switched.

## Making It Ask Before It Acts

- The messenger helper used to send the moment it decided to — no pause, no check-in.
- Now, instead of actually sending anything, it first shows you exactly what it's about to send
  and stops. Nothing goes out yet.
- You're then given exactly three choices — Send it, Edit, or Cancel — not a text box where you
  have to phrase your answer just right.
- Choosing Send or Cancel doesn't involve the AI at all at that point — it's a plain, direct,
  guaranteed decision, not something being interpreted or guessed at.
- Choosing Edit lets you describe a change, and the helper drafts a new version and shows you
  the same three choices again — so you can revise something more than once before deciding.
- We deliberately didn't build this as "type yes to confirm," because free text is fuzzy — a
  perfectly reasonable reply like "sure, go ahead" might not match whatever exact words the
  system was expecting. Three fixed choices remove that guesswork entirely.
- This only applies to the messenger helper, since it's the only one that actually *does*
  something in the real world. The other three only ever answer questions, so there's nothing
  for them to pause and check with you about.

## Optimization

- When one question needed several different lookups at once (like checking tickets, code
  commits, and notes all for one comparison), the helper used to do them one at a time, waiting
  for each to finish before starting the next. Now it starts all of them at the same time and
  waits only for the slowest one, instead of adding up every wait one after another.
- The work-activity and database helpers now remember what they already looked up earlier in the
  same conversation. So if a follow-up question needs the same information again, it reuses what
  it already found instead of looking it up all over again from scratch.

## Future Scope

- The evaluation steps described above only ran once, by hand, against a fixed set of example
  questions for three of the four helpers — there's no automatic check yet that re-runs those
  tests on every future change and flags a new mistake the moment it's introduced.
- A simple website version has been built and put online, but nobody has walked through the whole
  real flow — logging in, asking a question, watching the answer stream in, confirming a send —
  from an actual browser against the live version yet. Only quick spot-checks have been done there
  so far.
- Memory doesn't survive closing the program yet — it only lasts for one running session.
- Caching the user questions (related to Database agent only) and their SQL to save cost on 1 LLM call.