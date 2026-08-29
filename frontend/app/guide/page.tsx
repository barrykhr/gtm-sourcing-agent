import Link from "next/link";

type Shot = { src: string; alt: string };

function Section({
  id,
  eyebrow,
  title,
  what,
  how,
  shots,
  note,
}: {
  id: string;
  eyebrow: string;
  title: string;
  what: string;
  how: string[];
  shots: Shot[];
  note?: string;
}) {
  return (
    <section id={id} className="scroll-mt-20 border-t border-zinc-200 pt-8 dark:border-zinc-800">
      <p className="text-xs font-semibold uppercase tracking-wide text-indigo-700 dark:text-indigo-400">{eyebrow}</p>
      <h2 className="mt-1 text-xl font-semibold tracking-tight">{title}</h2>
      <p className="mt-2 max-w-2xl text-sm text-zinc-600 dark:text-zinc-400">{what}</p>
      <ol className="mt-4 flex max-w-2xl flex-col gap-1.5 text-sm">
        {how.map((step, i) => (
          <li key={i} className="flex gap-2">
            <span className="text-zinc-400 dark:text-zinc-600">{i + 1}.</span>
            <span>{step}</span>
          </li>
        ))}
      </ol>
      {note && (
        <p className="mt-3 max-w-2xl rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400">
          {note}
        </p>
      )}
      <div className="mt-4 flex flex-col gap-4">
        {shots.map((s) => (
          <div key={s.src} className="overflow-hidden rounded-lg border border-zinc-200 shadow-sm dark:border-zinc-800">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={s.src} alt={s.alt} className="w-full" />
          </div>
        ))}
      </div>
    </section>
  );
}

const TOC = [
  { id: "getting-started", label: "Getting started" },
  { id: "dashboard", label: "Dashboard" },
  { id: "overview", label: "Overview" },
  { id: "hiring-intelligence", label: "Hiring Intelligence" },
  { id: "talent-map", label: "Talent Map" },
  { id: "sourcing", label: "Sourcing" },
  { id: "candidates", label: "Candidates" },
  { id: "outreach", label: "Outreach" },
  { id: "pipeline", label: "Pipeline" },
  { id: "analytics", label: "Analytics" },
  { id: "copilot", label: "AI Copilot" },
  { id: "roster", label: "Candidates (global)" },
] as const;

export default function GuidePage() {
  return (
    <div className="flex flex-col gap-2 lg:flex-row lg:gap-10">
      <aside className="lg:sticky lg:top-8 lg:h-fit lg:w-48 lg:shrink-0">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">On this page</p>
        <nav className="flex flex-col gap-1 text-sm">
          {TOC.map((t) => (
            <a key={t.id} href={`#${t.id}`} className="text-zinc-500 hover:text-indigo-700 dark:hover:text-indigo-400">
              {t.label}
            </a>
          ))}
        </nav>
      </aside>

      <div className="min-w-0 flex-1">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight">Guide</h1>
          <p className="mt-1 max-w-2xl text-sm text-zinc-500">
            What every screen in Talyn does and how to use it — a walkthrough of the product as it
            exists today, not a marketing pitch for what it might become. Screenshots below are from a real
            session, captured in this app.
          </p>
        </div>

        <div className="mb-10 overflow-hidden rounded-lg border border-zinc-200 shadow-sm dark:border-zinc-800">
          <video controls preload="metadata" className="w-full bg-black">
            <source src="/guide/walkthrough.webm" type="video/webm" />
            Your browser can&apos;t play this video — the screenshots in each section below cover the same
            walkthrough.
          </video>
          <p className="border-t border-zinc-200 bg-zinc-50 px-3 py-2 text-xs text-zinc-500 dark:border-zinc-800 dark:bg-zinc-900">
            A real screen recording of one continuous session in this app — sign-in through every tab, the
            Copilot, and the global roster. Not a scripted demo video; the same actions described below.
          </p>
        </div>

        <Section
          id="getting-started"
          eyebrow="Account"
          title="Signing in"
          what="A shared recruiting workspace — every logged-in account sees the same jobs and candidates, there's no per-user data isolation."
          how={[
            "Visit the app and pick “Create account” to set up your own login (email + an 8+ character password), or “Log in” if you already have one.",
            "A teammate creates their own account the same way — everyone shares one workspace, not separate ones.",
            "Your session stays signed in across page reloads (an HTTP-only cookie, not something stored in the page). Use “Log out” in the top-right to end it.",
          ]}
          shots={[{ src: "/guide/00-login.png", alt: "Login / signup page" }]}
        />

        <Section
          id="dashboard"
          eyebrow="Home screen"
          title="Dashboard"
          what="Every hiring assignment is a persistent job workspace, not a chat thread. The dashboard lists every job you've created and lets you start a new one."
          how={[
            "Type a role title (and optionally a role family, e.g. “sales”) and click “New job” to create a workspace.",
            "Click any existing job card to reopen its workspace — nothing is lost between sessions, it's all saved.",
            "Once you have at least one job, a stat strip appears showing totals across every job: candidates evaluated, tier distribution, and how many recruiter decisions have been recorded vs. are still pending.",
          ]}
          shots={[
            { src: "/guide/01-dashboard-empty.png", alt: "Empty jobs dashboard" },
            { src: "/guide/17-dashboard-analytics.png", alt: "Dashboard with the cross-job analytics stat strip" },
          ]}
        />

        <Section
          id="overview"
          eyebrow="Job workspace · tab 1"
          title="Overview — JD intake"
          what="Paste a job description here first — every other tab in the workspace builds on what this stage extracts (must-haves, contradictions, missing information)."
          how={[
            "Paste the full job description text into the box.",
            "Click “Analyse JD”. This is the one stage that must run before any other tab has anything to work with.",
            "Read what comes back carefully — it explicitly flags contradictions (e.g. conflicting seniority language) and information the JD never specified, instead of silently guessing.",
          ]}
          shots={[
            { src: "/guide/02-overview-empty.png", alt: "Overview tab before analysis, with the JD paste box" },
            { src: "/guide/03-overview-intake.png", alt: "Overview tab after JD analysis" },
          ]}
        />

        <Section
          id="hiring-intelligence"
          eyebrow="Job workspace · tab 2"
          title="Hiring Intelligence"
          what="Two steps that turn a JD into criteria you can actually screen against: hiring-manager calibration (must-haves, red flags, what a strong vs. weak candidate looks like) and the resulting Ideal Candidate Profile."
          how={[
            "Click “Run calibration” — this reads the JD and produces evaluation criteria, red flags, and example interview questions.",
            "Click “Build hiring profile” to generate the ICP: must-have, nice-to-have, transferable, and disqualifying signals, refined from calibration.",
            "Candidates can't be added to this job until the hiring profile exists — it's what every candidate gets evaluated against.",
          ]}
          shots={[{ src: "/guide/04-hiring-intelligence.png", alt: "Hiring Intelligence tab with calibration and ICP" }]}
        />

        <Section
          id="talent-map"
          eyebrow="Job workspace · tab 3"
          title="Talent Map"
          what="A list of target companies worth sourcing from, each with a tier and the stated reason it's relevant — not just a list of logos."
          how={[
            "Click “Build talent map” once the hiring profile exists.",
            "Use the tiers to prioritize which companies to search first.",
          ]}
          shots={[{ src: "/guide/05-talent-map.png", alt: "Talent Map tab with tiered target companies" }]}
        />

        <Section
          id="sourcing"
          eyebrow="Job workspace · tab 4"
          title="Sourcing"
          what="Turns the talent map into literal search strings — boolean queries and exact target titles ready to paste into LinkedIn or another sourcing tool."
          how={[
            "Click “Create sourcing strategy”.",
            "Copy the boolean string directly into LinkedIn Recruiter (or wherever you search) — nothing here runs a real search for you yet.",
          ]}
          note="Search execution isn't built — this produces the query, you still run it yourself in your sourcing tool of choice."
          shots={[{ src: "/guide/06-sourcing.png", alt: "Sourcing tab with a boolean search string" }]}
        />

        <Section
          id="candidates"
          eyebrow="Job workspace · tab 5"
          title="Candidates"
          what="Every candidate for this job, as a real table: tier, pipeline stage, and outreach status at a glance. Click a name to see full evidence, prioritize them, and record your own decision on them."
          how={[
            "Click “+ Add candidate” and paste resume text, a LinkedIn profile, or recruiter notes, plus a role family. A source URL is optional but enables cross-job dedup (see “Candidates (global)” below).",
            "Click “Prioritize” to get a tier (A–D) with rationale, what's still unknown, and what to validate in screening.",
            "Click a candidate's name to expand their row: achievements and metrics are labeled VERIFIED, INFERRED, or left absent — never presented as fact when they're a guess.",
            "In the expanded row, use “Recruiter decision” to record what you decided — Pursue, Pass for now, Revisit later, or your own custom text. This is the only thing that can move someone out of consideration; nothing here rejects a candidate automatically.",
            "If this person has been evaluated on another job before, a “Seen before” card shows their prior tier and decision right here — see “Candidates (global)” for how that dedup works.",
          ]}
          shots={[
            { src: "/guide/07-candidates-table.png", alt: "Candidates tab table view" },
            { src: "/guide/08-candidates-decision.png", alt: "Candidate expanded with evidence and recruiter decision" },
          ]}
        />

        <Section
          id="outreach"
          eyebrow="Job workspace · tab 6"
          title="Outreach"
          what="Drafts a full outreach sequence per candidate — LinkedIn note, InMail, email, two follow-ups — personalized from their verified evidence."
          how={[
            "Click “Generate outreach” for a candidate to draft the sequence.",
            "Copy whichever draft you want to actually use — into LinkedIn, your email client, wherever you're reaching out from.",
            "Once you've genuinely sent something yourself, click “Mark as sent”. This records when, and — if they haven't reached Contacted yet — moves them there on the Pipeline board automatically.",
          ]}
          note="Nothing here sends anything. There is no email or LinkedIn integration — “Mark as sent” records that you did it yourself, it doesn't do it for you."
          shots={[
            { src: "/guide/09-outreach-drafted.png", alt: "Outreach tab with a drafted sequence" },
            { src: "/guide/10-outreach-sent.png", alt: "Outreach tab after marking a draft sent" },
          ]}
        />

        <Section
          id="pipeline"
          eyebrow="Job workspace · tab 7"
          title="Pipeline"
          what="A column board across all twelve funnel stages, from Identified to Joined. Every move is kept in a timestamped history you can review."
          how={[
            "Use “‹ back” / “next ›” on a candidate's card to move them a stage at a time.",
            "Click a candidate's name to expand their card: it shows how long they've been in the current stage and their full move history.",
            "Add an optional note before your next move (e.g. why someone was passed on) — it's saved with that specific transition and shown in the history.",
          ]}
          shots={[
            { src: "/guide/11-pipeline-board.png", alt: "Pipeline board with columns per funnel stage" },
            { src: "/guide/12-pipeline-history.png", alt: "Expanded pipeline card showing stage history" },
          ]}
        />

        <Section
          id="analytics"
          eyebrow="Job workspace · tab 8"
          title="Analytics"
          what="This job's funnel: counts and conversion rates at every stage, plus which transition is leaking the most candidates."
          how={[
            "No action needed — this updates automatically as candidates move through the pipeline.",
            "The leakage insight is arithmetic over your own funnel data, not a separate AI judgment — it's labeled as such so it's never mistaken for one.",
          ]}
          shots={[{ src: "/guide/13-analytics-tab.png", alt: "Analytics tab with funnel counts and conversion rates" }]}
        />

        <Section
          id="copilot"
          eyebrow="Available from any tab"
          title="AI Copilot"
          what="A command layer over the job, not a replacement for it. Ask it questions about the job or ask it to propose a change — it never applies anything without you approving it first."
          how={[
            "Click “AI Copilot” in the workspace header to open it as a panel over whatever tab you're on.",
            "Ask about the job (“who have we got so far?”) or ask it to propose a requirement change (“remove Fabric as a mandatory requirement”).",
            "A proposed change shows what it would do and its impact before anything happens — click “Yes — apply” to confirm it, or “No” to decline.",
          ]}
          shots={[{ src: "/guide/14-copilot-panel.png", alt: "AI Copilot panel open over the Analytics tab" }]}
        />

        <Section
          id="roster"
          eyebrow="Top nav"
          title="Candidates (global)"
          what="Every person you've ever evaluated, across every job — deduplicated into one profile with their full cross-job fit history, not a separate disconnected record per job."
          how={[
            "Click “Candidates” in the top nav to see the full roster.",
            "Click a person to see every job they've been evaluated for, with the tier and rationale specific to each one.",
            "Dedup runs automatically when you add a candidate: an identical source URL matches first; otherwise a normalized name+company match is used. It's never silent — a match is always logged.",
          ]}
          shots={[
            { src: "/guide/15-global-roster.png", alt: "Global candidates roster" },
            { src: "/guide/16-candidate-profile.png", alt: "Candidate profile with cross-job evaluation history" },
          ]}
        />

        <div className="mt-10 border-t border-zinc-200 pt-6 text-xs text-zinc-400 dark:border-zinc-800">
          <p>
            Every screenshot above was captured from this app, in one real session — not mocked up separately.
            Have a question this guide doesn&apos;t answer?{" "}
            <Link href="/" className="text-indigo-700 hover:underline dark:text-indigo-400">
              Head back to your jobs
            </Link>{" "}
            and ask the AI Copilot from any workspace.
          </p>
        </div>
      </div>
    </div>
  );
}
