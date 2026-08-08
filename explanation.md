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

## What's Done So Far

- The traffic cop that routes questions to the right helper — working and tested.
- The document reader helper — working and tested with real company-style documents.
- The work activity reader helper — working and tested with the pretend company's data.
- The database reader helper — working and tested with a pretend company database.
- All three helpers give honest answers and admit when they don't know something.

## What's Left To Build

- One more helper hasn't been built yet — for sending messages (like Slack or email).
- There's no automatic way yet to catch every mistake — most problems so far were found by
  manually asking tricky questions and checking the answers by hand.
- A simple website interface hasn't been built yet — right now it only works through a
  typed chat window.
