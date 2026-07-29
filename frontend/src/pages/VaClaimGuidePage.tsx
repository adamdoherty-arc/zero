import { createContext, useContext, useEffect, useMemo } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Circle, ExternalLink as ExternalLinkIcon } from 'lucide-react'
import { usePersonalWorkItems } from '@/hooks/usePersonalWorkItemsApi'
import { VA_GUIDE_SECTIONS } from '@/config/vaClaimGuide'

/** Maps task id -> status, so the guide can show a checkmark for tasks that
 *  are already done without threading the prop through every Section call. */
const TaskStatusContext = createContext<Record<string, string>>({})

function TaskCheckmark({ taskId }: { taskId: string }) {
  const statusById = useContext(TaskStatusContext)
  const done = statusById[taskId] === 'done'
  return done ? (
    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
  ) : (
    <Circle className="w-4 h-4 text-gray-700 shrink-0" />
  )
}

function ExternalLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 hover:underline break-all"
    >
      {children}
      <ExternalLinkIcon className="w-3 h-3 shrink-0" />
    </a>
  )
}

function BoardLink({ taskId }: { taskId: string }) {
  const statusById = useContext(TaskStatusContext)
  const done = statusById[taskId] === 'done'
  return (
    <Link
      to={`/va-claim?task=${taskId}`}
      className={`inline-flex items-center gap-1.5 text-sm hover:underline ${
        done ? 'text-emerald-400 hover:text-emerald-300' : 'text-indigo-400 hover:text-indigo-300'
      }`}
    >
      <TaskCheckmark taskId={taskId} />
      {done ? 'Done — view on board' : 'Open this task on the board'} →
    </Link>
  )
}

function Section({
  id,
  index,
  title,
  taskId,
  children,
}: {
  id: string
  index: number
  title: string
  taskId?: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="glass-card p-6 scroll-mt-20">
      <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <h2 className="text-lg font-semibold text-white">
          <span className="text-gray-500 mr-2">{index}.</span>
          {title}
        </h2>
        {taskId && <BoardLink taskId={taskId} />}
      </div>
      <div className="space-y-3 text-sm text-gray-300 leading-relaxed">{children}</div>
    </section>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="text-xs uppercase tracking-wider text-gray-500">{label}</span>
      <div className="mt-0.5">{children}</div>
    </div>
  )
}

export function VaClaimGuidePage() {
  const location = useLocation()
  const { data: tasks = [] } = usePersonalWorkItems({ topic: 'VA Claim' })
  const statusById = useMemo(
    () => Object.fromEntries(tasks.map((t) => [t.id, t.status])),
    [tasks],
  )
  const doneCount = VA_GUIDE_SECTIONS.filter((s) => statusById[s.taskIds[0]] === 'done').length

  // React Router doesn't auto-scroll to a #hash on route entry — do it manually.
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [location.hash])

  return (
    <TaskStatusContext.Provider value={statusById}>
    <div className="page-content space-y-4 max-w-4xl">
      <div>
        <Link to="/va-claim" className="inline-flex items-center gap-1 text-sm text-indigo-400 hover:underline mb-2">
          <ArrowLeft className="w-4 h-4" /> Back to VA Claim board
        </Link>
        <h1 className="text-2xl font-semibold text-white">VA Claim Guide</h1>
        <p className="text-sm text-gray-400 max-w-3xl">
          A plain-English explanation of every form, appointment, and piece of evidence on your VA Claim board — what
          it is, why it matters for your rating, and exactly where to go to get it done. Not legal or medical advice;
          your CVSO/VSO is the authoritative source for anything form- or deadline-specific. Government sites
          occasionally restructure their URLs — if a link below 404s, search the form number directly on{' '}
          <ExternalLink href="https://www.va.gov/find-forms/">va.gov/find-forms</ExternalLink> or ask your VSO.
        </p>
      </div>

      {/* Table of contents — doubles as a checklist against live task status */}
      <div className="glass-card p-4">
        <h2 className="text-xs uppercase tracking-wider text-gray-500 mb-2">
          Jump to <span className="text-gray-600">({doneCount}/{VA_GUIDE_SECTIONS.length} done)</span>
        </h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1.5">
          {VA_GUIDE_SECTIONS.map((s, i) => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className="inline-flex items-center gap-1.5 text-sm text-gray-300 hover:text-indigo-400 truncate"
            >
              <TaskCheckmark taskId={s.taskIds[0]} />
              {i + 1}. {s.title}
            </a>
          ))}
        </div>
      </div>

      {/* Quick reference: every form/site that recurs across sections */}
      <div className="glass-card p-6">
        <h2 className="text-lg font-semibold text-white mb-3">Quick reference — forms &amp; accounts</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm text-left">
            <thead className="text-xs uppercase tracking-wider text-gray-500 border-b border-gray-800">
              <tr>
                <th className="py-2 pr-4">Form / Site</th>
                <th className="py-2 pr-4">What it's for</th>
                <th className="py-2">Link</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">21-0966</td>
                <td className="py-2 pr-4">Intent to File (locks your effective date)</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/resources/your-intent-to-file-a-va-claim/">va.gov ITF</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">21-526EZ</td>
                <td className="py-2 pr-4">The main disability compensation claim</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/disability/file-disability-claim-form-21-526ez/introduction">va.gov file-claim wizard</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">21-22</td>
                <td className="py-2 pr-4">Power of Attorney for your VSO</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/find-forms/about-form-21-22/">va.gov about-form-21-22</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">21-10210</td>
                <td className="py-2 pr-4">Buddy / lay statement</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/find-forms/about-form-21-10210/">va.gov about-form-21-10210</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">21-4138</td>
                <td className="py-2 pr-4">Personal statement in support of claim</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/find-forms/about-form-21-4138/">va.gov about-form-21-4138</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">10-10EZ</td>
                <td className="py-2 pr-4">VA health care enrollment application</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/health-care/apply/">va.gov health-care apply</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">SF-180 / eVetRecs</td>
                <td className="py-2 pr-4">Request OMPF + STRs (NARA)</td>
                <td className="py-2"><ExternalLink href="https://vetrecs.archives.gov">vetrecs.archives.gov</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">milConnect / DPRIS</td>
                <td className="py-2 pr-4">Fastest path to DD-214 + STRs (post-1995 Navy)</td>
                <td className="py-2"><ExternalLink href="https://milconnect.dmdc.osd.mil">milconnect.dmdc.osd.mil</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">Accreditation search</td>
                <td className="py-2 pr-4">Verify any VSO/attorney is legit before signing a POA</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/ogc/apps/accreditation/">va.gov accreditation search</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">Track Claims</td>
                <td className="py-2 pr-4">Check claim status once filed</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/track-claims/">va.gov track-claims</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">DBQs</td>
                <td className="py-2 pr-4">The exact checklists C&amp;P examiners fill out</td>
                <td className="py-2"><ExternalLink href="https://www.benefits.va.gov/compensation/dbq_publicdbqs.asp">public DBQ list</ExternalLink></td>
              </tr>
              <tr>
                <td className="py-2 pr-4 font-medium text-white whitespace-nowrap">Decision Reviews</td>
                <td className="py-2 pr-4">Supplemental Claim (20-0995) / HLR (20-0996) / Board Appeal (10182)</td>
                <td className="py-2"><ExternalLink href="https://www.va.gov/decision-reviews/">va.gov decision-reviews</ExternalLink></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="text-xs text-gray-500 mt-3">
          Legal citations below (38 U.S.C., 38 C.F.R.) link to Cornell Law School's free Legal Information Institute.
          For case law (Mittleider v. West, BVA decisions), search{' '}
          <ExternalLink href="https://www.courtlistener.com">CourtListener</ExternalLink> or the official{' '}
          <ExternalLink href="https://www.index.va.gov/search/va/bva.jsp">BVA decision search</ExternalLink> — ask
          your VSO to pull the exact citation if you can't find it.
        </p>
      </div>

      <Section id="strategy" index={1} title="Overall strategy (TL;DR)" taskId="ptask-b4d69d8ed04c">
        <p>
          You're filing one consolidated claim for three conditions that are legally linked to each other: GERD /
          hiatal hernia (direct service connection), anxiety (secondary to the GI condition), and tinnitus (direct
          service connection from Navy noise exposure).
        </p>
        <Field label="Why file all three together">
          They share one claim number, one effective date, and the anxiety claim is legally dependent on the GI
          claim being service-connected first (secondary connection under{' '}
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.310">38 C.F.R. § 3.310</ExternalLink>).
        </Field>
        <Field label="Realistic outcome">
          A combined rating of roughly 50%–70% (see the <a href="#rating-tracker" className="text-indigo-400 hover:underline">rating tracker</a> for the math), worth
          $1,132.90–$1,808.45/month at 2026 single-veteran rates.
        </Field>
        <Field label="The one thing that moves the needle most">
          A documented esophageal stricture or dilatation from an EGD — see{' '}
          <a href="#gi-consult" className="text-indigo-400 hover:underline">GI consult + EGD</a>. Get this done before your C&amp;P exam.
        </Field>
        <Field label="Free help first, always">
          A CVSO/DAV representative is free and legally required for real for initial claims — attorneys can't
          charge for this stage under{' '}
          <ExternalLink href="https://www.law.cornell.edu/uscode/text/38/5904">38 U.S.C. § 5904</ExternalLink>. See{' '}
          <a href="#cvso-poa" className="text-indigo-400 hover:underline">CVSO / POA</a>.
        </Field>
      </Section>

      <Section id="intent-to-file" index={2} title="Intent to File — VA Form 21-0966" taskId="ptask-6d5818a69ce4">
        <Field label="What it is">
          A one-page placeholder that tells the VA "I'm filing a claim" without requiring the claim itself yet. It
          exists purely to lock in a date.
        </Field>
        <Field label="Why it matters">
          Under <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.155">38 C.F.R. § 3.155(b)</ExternalLink>, if you submit the full 21-526EZ within 365 days of
          filing the ITF, VA back-dates your effective date (and therefore your back-pay) to the ITF date — not the
          later date you actually finish the paperwork. This is why it was the first thing you filed.
        </Field>
        <Field label="Status">
          Already done (2026-06-20). Your 365-day clock to submit the 21-526EZ runs to roughly{' '}
          <span className="text-white font-medium">2027-06-20</span>. Filing the 526EZ earlier does not increase
          back-pay — it just locks in the same effective date sooner, so there is no rush on this specific point;
          spend the time building evidence instead.
        </Field>
        <Field label="Where it lives">
          <ExternalLink href="https://www.va.gov/resources/your-intent-to-file-a-va-claim/">va.gov — Intent to File</ExternalLink> (auto-created
          when you start a 21-526EZ online), or by phone at 1-800-827-1000.
        </Field>
      </Section>

      <Section id="digital-accounts" index={3} title="Digital accounts (VA.gov, MyHealtheVet, milConnect, eVetRecs)" taskId="ptask-fb6be90fa7cc">
        <p>Four separate federal logins you need before you can pull records or file anything online.</p>
        <Field label="VA.gov — the claim itself">
          Sign in with Login.gov or ID.me (same-day verification). This is where you file the 21-526EZ and check
          status. <ExternalLink href="https://www.va.gov">va.gov</ExternalLink>
        </Field>
        <Field label="MyHealtheVet — your VA medical records">
          "Blue Button" lets you download everything VA has on file for you once you're enrolled in VA health care.{' '}
          <ExternalLink href="https://www.myhealth.va.gov">myhealth.va.gov</ExternalLink>
        </Field>
        <Field label="milConnect (DPRIS) — fastest records path">
          Go to Correspondence/Documentation → DPRIS → Personnel File. This is the quickest way to pull your DD-214
          and Service Treatment Records if you served after 1995. <ExternalLink href="https://milconnect.dmdc.osd.mil">milconnect.dmdc.osd.mil</ExternalLink>
        </Field>
        <Field label="eVetRecs — backup records path">
          National Archives' request portal for your Official Military Personnel File (OMPF). Slower (2–4 weeks
          standard) but works if milConnect stalls. <ExternalLink href="https://vetrecs.archives.gov">vetrecs.archives.gov</ExternalLink>
        </Field>
        <p className="text-xs text-gray-500">Use the same email on all four so VA can match your identity across systems.</p>
      </Section>

      <Section id="ompf-strs" index={4} title="OMPF + Service Treatment Records (STRs)" taskId="ptask-ea9e75a0210a">
        <Field label="What these are">
          Your Official Military Personnel File (OMPF) and Service Treatment Records (STRs) — the actual paperwork
          from your time in the Navy: sick-call visits, prescriptions, the surgical report, and your DD-214.
        </Field>
        <Field label="Why they're non-negotiable">
          VA requires proof of an in-service event to grant direct service connection (
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.303">38 C.F.R. § 3.303</ExternalLink>). Only your STRs can prove the INH
          prescription, the hiatal hernia workup, and the Nissen fundoplication actually happened while you were
          serving.
        </Field>
        <Field label="Fastest path">
          milConnect → DPRIS → Personnel File (see <a href="#digital-accounts" className="text-indigo-400 hover:underline">digital accounts</a> above) — typically days to a
          couple weeks for Navy service after 1995.
        </Field>
        <Field label="Backup paths">
          <ul className="list-disc list-inside space-y-1">
            <li><ExternalLink href="https://vetrecs.archives.gov">NARA eVetRecs</ExternalLink> — 2–4 weeks standard, 1–5 days if flagged emergency</li>
            <li>Mail/fax an SF-180 to NPRC, 1 Archives Drive, St. Louis, MO 63138 / Fax 314-801-9195 (4–8 weeks)</li>
            <li>Navy Personnel Command (PERS-313), 5720 Integrity Drive, Millington, TN 38055</li>
          </ul>
        </Field>
        <Field label="What to look for once received">
          Date/provider of the INH prescription, hiatal hernia workup dates, the Nissen operative report (surgeon,
          hospital, date), post-op follow-up notes, and your DD-214's AE rating line (for the tinnitus claim).
        </Field>
      </Section>

      <Section id="va-health-care" index={5} title="VA health care enrollment" taskId="ptask-f94d26c40b2f">
        <Field label="What it is">
          Separate from disability compensation — this enrolls you in VA's health care system (Form 10-10EZ), which
          is what gets you seen by a VA GI specialist.
        </Field>
        <Field label="Why apply even though it's not about GERD directly">
          Enrollment opens the door to a VA GI clinic that can perform the EGD that documents your esophageal
          stricture — the single biggest lever for the GI rating (see{' '}
          <a href="#gi-consult" className="text-indigo-400 hover:underline">GI consult + EGD</a>). PACT-Act era service (Aug 2, 1990 or Sept 11, 2001
          onward, in a listed toxic-exposure location) also grants automatic eligibility and future presumptive
          coverage if any PACT-listed condition develops later.
        </Field>
        <Field label="Where to apply">
          <ExternalLink href="https://www.va.gov/health-care/apply/">va.gov — apply for VA health care</ExternalLink>. Bring your
          DD-214 (order via milConnect if you don't have a copy).
        </Field>
      </Section>

      <Section id="cvso-poa" index={6} title="CVSO / DAV appointment + Power of Attorney — VA Form 21-22" taskId="ptask-48def01570b4">
        <Field label="What a CVSO/VSO actually does">
          A County Veterans Service Officer or Veteran Service Organization rep is a federally accredited advocate
          who reviews your claim before it's submitted, certifies it as "fully developed," and can communicate with
          VA on your behalf. Signing VA Form 21-22 authorizes them to do this.
        </Field>
        <Field label="Why it's free">
          By law (<ExternalLink href="https://www.law.cornell.edu/uscode/text/38/5904">38 U.S.C. § 5904</ExternalLink>), no attorney can
          charge a fee for an initial claim — only after a decision has been made and you're appealing. CVSOs and
          VSOs do this work for free, full time.
        </Field>
        <Field label="Top local choice — Duval CVSO">
          City of Jacksonville Military Affairs &amp; Veterans Department (MAVD), 117 W. Duval St., Suite 175,
          Jacksonville, FL 32202. <span className="text-white">(904) 255-5550</span> · vetsvcs@coj.net · Mon–Fri
          7:00 AM–3:00 PM, walk-ins accepted (appointment preferred).
        </Field>
        <Field label="National backups">
          <ExternalLink href="https://www.dav.org/find-your-local-office/">DAV — find your local office</ExternalLink>,{' '}
          <ExternalLink href="https://www.legion.org/serviceofficers">American Legion service officers</ExternalLink>, or VFW Post 3270
          (Jax Beach) at (904) 249-7366.
        </Field>
        <Field label="Before you sign anything">
          Verify the rep is currently accredited at{' '}
          <ExternalLink href="https://www.va.gov/ogc/apps/accreditation/">va.gov accreditation search</ExternalLink> — takes 30 seconds and
          protects you from accreditation fraud.
        </Field>
        <Field label="At the appointment, ask specifically">
          Whether your file qualifies for a Decision Ready Claim (DRC) — VA has committed to deciding these in a
          much shorter window than the ~76-day average for a standard Fully Developed Claim.
        </Field>
      </Section>

      <Section id="gi-consult" index={7} title="GI consult + EGD / barium swallow — the biggest rating lever" taskId="ptask-c2fa773ea065">
        <Field label="Why this one task matters more than any other">
          Your GERD claim is rated under Diagnostic Code 7206 (rewritten May 19, 2024), which grades you on
          documented findings, not on how bad symptoms feel. Without an EGD on record, a rater has nothing to point
          to except "takes a daily PPI" — which caps you at 10%.
        </Field>
        <Field label="The DC 7206 rating ladder">
          <ul className="list-disc list-inside space-y-1">
            <li><span className="text-white">10%</span> — daily PPI to control symptoms, otherwise asymptomatic</li>
            <li><span className="text-white">30%</span> — dilatation 3+/year, OR dilatation with steroids ≥1/yr, OR a stent</li>
            <li><span className="text-white">50%</span> — dilatation, but only 1–2 times per year</li>
            <li><span className="text-white">80%</span> — aspiration, malnutrition, major weight loss, surgical correction, or a feeding tube</li>
          </ul>
        </Field>
        <Field label="What to ask for">
          An upper endoscopy (EGD) with biopsies, and a barium swallow (esophagram) if swallowing trouble is
          prominent. Get this through the VA GI clinic (once{' '}
          <a href="#va-health-care" className="text-indigo-400 hover:underline">VA health care</a> is approved) or a private gastroenterologist —
          whichever is faster.
        </Field>
        <Field label="Bring this to the appointment">
          Nightly heartburn frequency, daily PPI dose, dysphagia episodes, food impactions, regurgitation, sleep
          disruption, chest pain after meals. This becomes the exam roadmap for both the GI doctor and, later, the
          C&amp;P examiner.
        </Field>
      </Section>

      <Section id="buddy-statements" index={8} title="Buddy statements — VA Form 21-10210" taskId="ptask-6fad49e1fca7">
        <Field label="What this is">
          Short, signed statements from 1–3 people who personally witnessed your symptoms or service conditions —
          counted as evidence under{' '}
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.159">38 C.F.R. § 3.159(a)(2)</ExternalLink>.
        </Field>
        <Field label="Who to ask">
          <ul className="list-disc list-inside space-y-1">
            <li>Spouse/partner/housemate — nightly observer of reflux, sleep position, anxiety around eating (most valuable)</li>
            <li>A shipmate from USS Enterprise — corroborates GI onset timing and noise exposure conditions</li>
            <li>A family member who knew you before and after service — establishes the "no baseline problem" contrast</li>
          </ul>
        </Field>
        <Field label="Get the form">
          <ExternalLink href="https://www.va.gov/find-forms/about-form-21-10210/">va.gov — about Form 21-10210</ExternalLink>. Keep every
          account consistent with your <a href="#personal-statement" className="text-indigo-400 hover:underline">personal statement</a> and
          <a href="#narrative-gerd" className="text-indigo-400 hover:underline"> narratives</a> — inconsistencies are exactly what a rater looks for.
        </Field>
      </Section>

      <Section id="personal-statement" index={9} title="Personal statement — VA Form 21-4138" taskId="ptask-7ce2d37358e7">
        <Field label="What this is">
          Your own written account of your conditions and how they connect to service — in your own words, signed
          and dated, submitted alongside the main claim.
        </Field>
        <Field label="Status">
          A full draft already exists on the board task — it covers all three conditions (GI, anxiety, tinnitus)
          with bracketed placeholders for dates and specifics you need to fill in.
        </Field>
        <Field label="What's left">
          Fill every [bracket] with real dates/facts, keep it word-for-word consistent with the three narrative
          tasks and buddy statements, then sign and date it.
        </Field>
        <Field label="Get the blank form">
          <ExternalLink href="https://www.va.gov/find-forms/about-form-21-4138/">va.gov — about Form 21-4138</ExternalLink>
        </Field>
      </Section>

      <Section id="evidence-packet" index={10} title="Medical evidence packet" taskId="ptask-52b5b8765666">
        <Field label="What this is">
          A single organized PDF bundling every piece of medical evidence, submitted together with the 21-526EZ.
        </Field>
        <Field label="What goes in it">
          <ul className="list-disc list-inside space-y-1">
            <li>DD-214 (front and back)</li>
            <li>OMPF excerpt confirming your AE rating</li>
            <li>In-service INH prescription record</li>
            <li>Nissen fundoplication operative report + post-op follow-up notes</li>
            <li>Current GI records (last 12 months): EGD, barium swallow, manometry, medication list</li>
            <li>Mental health records: diagnoses, prescriptions, treatment notes</li>
            <li>Any audiology records</li>
          </ul>
        </Field>
        <Field label="How to organize it">
          Chronological within each condition, tabbed/bookmarked by section, every page numbered. Your CVSO can
          advise on the exact upload format VA prefers.
        </Field>
      </Section>

      <Section id="gi-nexus" index={11} title="GI nexus letter" taskId="ptask-2811de903469">
        <Field label="What a 'nexus letter' is">
          A letter from a doctor that explicitly ties your current diagnosis to the in-service event, using the
          specific legal phrase "at least as likely as not (≥50% probability)." Without this exact phrasing, VA
          raters often won't credit the opinion.
        </Field>
        <Field label="Why it's the single most persuasive document in the GI claim">
          STRs prove something happened in service; a nexus letter is what a medical professional says connects that
          event to your condition today. Raters weigh nexus letters heavily.
        </Field>
        <Field label="Who to ask">
          Your treating GI specialist first (already knows your case). Backup: a paid independent medical examiner
          (IME), typically $400–$2,000.
        </Field>
        <Field label="What the letter needs">
          Clinician's credentials, records reviewed, current diagnoses, the "at least as likely as not" opinion
          sentence, a rationale citing supporting literature, and a signature with license number and date. A full
          template exists in the board task description — share it directly with the clinician.
        </Field>
      </Section>

      <Section id="anxiety-nexus" index={12} title="Anxiety nexus paragraph" taskId="ptask-3d6fa0d5fa47">
        <Field label="What this is">
          A shorter version of the nexus concept above, specifically linking your anxiety to your GI condition under{' '}
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.310">38 C.F.R. § 3.310</ExternalLink> (secondary service connection).
        </Field>
        <Field label="Why it's easier to get than the GI nexus letter">
          Most prescribers (psychiatrist or PCP) can write this during a routine visit — it's a short paragraph, not
          a formal medical-legal letter. A ready-to-use draft paragraph exists on the board task; just hand it to
          your prescriber to sign off on or adapt.
        </Field>
        <Field label="What to gather alongside it">
          Treatment notes showing diagnosis, panic-attack frequency, medication list with dosages, and (importantly)
          any prior records showing you had no pre-service anxiety history.
        </Field>
      </Section>

      <Section id="ae-rating" index={13} title="Verify AE rating (tinnitus)" taskId="ptask-55bcda074240">
        <Field label="Why tinnitus is close to a 'gimme'">
          Every Navy Aviation rating (AE, AB, ABE, ABF, ABH, AC, AD, AM, AME, AO, AS, AT, AW) is designated "Highly
          Probable" for hazardous noise exposure on VBA's Duty MOS Noise Exposure Listing — meaning VA generally
          concedes the in-service noise exposure without further argument, and{' '}
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.87">38 C.F.R. § 4.87</ExternalLink>, Diagnostic Code 6260, is a flat
          10% once service connection is granted.
        </Field>
        <Field label="What you actually need to do">
          Just confirm your DD-214 (line 12, rating at separation) shows AE. If it shows a different primary rating
          with AE as cross-trained, pull the OMPF page that documents the AE designation instead and save it as
          evidence.
        </Field>
        <Field label="Where the DD-214/OMPF documents already live">
          See <a href="#ompf-strs" className="text-indigo-400 hover:underline">OMPF + STRs</a> — same records request covers this.
        </Field>
      </Section>

      <Section id="form-526ez" index={14} title="Submit VA Form 21-526EZ — the main claim" taskId="ptask-13453b116577">
        <Field label="What this form actually is">
          "Application for Disability Compensation and Related Compensation Benefits" — this is THE claim. Everything
          else on this board (records, nexus letters, statements, evidence packet) exists to support this one
          submission.
        </Field>
        <Field label="Where it is / how to file it">
          File online (fastest, auto-tracks status):{' '}
          <ExternalLink href="https://www.va.gov/disability/file-disability-claim-form-21-526ez/introduction">va.gov guided claim wizard</ExternalLink>.
          Paper version and instructions: <ExternalLink href="https://www.va.gov/find-forms/about-form-21-526ez/">va.gov — about Form 21-526EZ</ExternalLink>.
          In practice, though, you'll sign this through your CVSO/VSO (see{' '}
          <a href="#cvso-poa" className="text-indigo-400 hover:underline">CVSO / POA</a>) — they submit it on your behalf and certify it.
        </Field>
        <Field label="Why file as a Fully Developed Claim (FDC), not Standard">
          FDC averages ~76 days because you submit all your own evidence upfront instead of waiting for VA to
          gather it — a Decision Ready Claim through your VSO can be even faster (often under 30 days).
        </Field>
        <Field label="What to attach">
          The medical evidence packet, GI nexus letter, anxiety nexus paragraph, buddy statements, personal
          statement, and your DD-214. Claim all three conditions in one submission.
        </Field>
        <Field label="The deadline that actually matters">
          Must be submitted within 365 days of your Intent to File (~2027-06-20) to keep the back-dated effective
          date — see <a href="#intent-to-file" className="text-indigo-400 hover:underline">Intent to File</a>.
        </Field>
        <Field label="After you submit">
          Track status at <ExternalLink href="https://www.va.gov/track-claims/">va.gov/track-claims</ExternalLink>. Get a confirmation
          receipt with your claim number from the CVSO.
        </Field>

        <div className="rounded-lg border border-amber-800 bg-amber-950/30 text-amber-200 px-4 py-3 text-sm">
          <span className="font-semibold text-amber-100">Don&apos;t file yet.</span> Your{' '}
          <a href="#gi-consult" className="underline hover:text-amber-100">GI consult / EGD</a> result is still the single
          biggest rating lever (Diagnostic Code 7206 — an undocumented case defaults to 10%; a documented stricture or
          dilatation reaches 30&ndash;50%). Get that first, then the nexus letters, then file &mdash; there&apos;s ~11 months of
          runway before the 2027-06-20 deadline.
        </div>

        <Field label="Exact wording — Disability 1: GERD / hiatal hernia / post-Nissen residuals">
          <div className="space-y-2">
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">Disability name (enter exactly)</span>
              <p className="font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2 mt-1">
                Gastroesophageal reflux disease (GERD) with hiatal hernia and post-surgical (laparoscopic Nissen
                fundoplication) dysphagia
              </p>
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">Type / date began</span>
              <p className="mt-1">
                New &mdash; direct service connection. Date began: <span className="text-amber-300">[exact date of the
                in-service INH prescription / onset of severe heartburn &mdash; pull from STRs]</span>.
              </p>
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">How it began</span>
              <p className="mt-1 font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2">
                I served aboard USS Enterprise (CVN-65) from 2014 to 2017, including a deployment to the 5th Fleet area
                of responsibility. During that period I developed severe heartburn and upper-abdominal pain. I was
                prescribed isoniazid (INH) <span className="text-amber-300">[for a positive PPD / TB prophylaxis &mdash;
                confirm]</span>, after which my stomach symptoms became markedly worse. On <span className="text-amber-300">[date]</span>{' '}
                I underwent a laparoscopic Nissen fundoplication at <span className="text-amber-300">[hospital]</span>. Since
                that surgery I have severe acid reflux every night that wakes me choking and burning, and lasting
                difficulty swallowing &mdash; food gets stuck and I have to eat slowly, wash it down, or bring it back up. My
                provider has told me this is permanent.
              </p>
            </div>
          </div>
        </Field>

        <Field label="Exact wording — Disability 2: Anxiety, secondary to Disability 1">
          <div className="space-y-2">
            <div className="rounded-lg border border-rose-800 bg-rose-950/30 text-rose-200 px-3 py-2 text-xs">
              <span className="font-semibold text-rose-100">The one place claims get lost:</span> a secondary condition
              must name the primary condition using the <span className="italic">identical wording</span> you used in
              Disability 1 above. If the two entries describe the primary condition differently, the rater can&apos;t
              reliably link them.
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">Disability name (enter exactly)</span>
              <p className="font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2 mt-1">
                Generalized anxiety disorder, secondary to service-connected gastroesophageal reflux disease (GERD)
                with hiatal hernia and post-surgical (Nissen fundoplication) dysphagia
              </p>
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">Type / authority</span>
              <p className="mt-1">
                New &mdash; secondary service connection under{' '}
                <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.310">38 C.F.R. § 3.310</ExternalLink>.
              </p>
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">How it began</span>
              <p className="mt-1 font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2">
                I had no history of anxiety before my GI condition. Waking up almost every night choking and burning on
                stomach acid, and never knowing when food will get stuck since the Nissen surgery, has made me anxious
                about eating, sleeping, and social situations involving food. I experience anxiety/panic symptoms
                approximately <span className="text-amber-300">[X times/week]</span>, with sleep disrupted by reflux{' '}
                <span className="text-amber-300">[X times/night]</span> and avoidance around restaurants and eating with
                others.
              </p>
            </div>
          </div>
        </Field>

        <Field label="Exact wording — Disability 3: Tinnitus, bilateral">
          <div className="space-y-2">
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">Disability name (enter exactly)</span>
              <p className="font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2 mt-1">Tinnitus, bilateral</p>
            </div>
            <div>
              <span className="text-xs uppercase tracking-wider text-gray-500">How it began</span>
              <p className="mt-1 font-mono text-xs bg-gray-900/60 border border-gray-800 rounded px-3 py-2">
                I served in the Navy <span className="text-amber-300">[rating &mdash; Aviation Electrician&apos;s Mate (AE)?
                confirm]</span> aboard USS Enterprise (CVN-65), 2014&ndash;2017. My duties exposed me to high-intensity
                noise on a near-daily basis <span className="text-amber-300">[flight-deck / hangar-bay / engine work &mdash;
                specify]</span>. I began noticing ringing in my ears during service and it has continued ever since &mdash;{' '}
                <span className="text-amber-300">[constant/intermittent, pitch]</span> &mdash; and it interferes with my sleep
                and concentration.
              </p>
            </div>
            <div className="text-xs text-gray-400">
              See <a href="#ae-rating" className="text-indigo-400 hover:underline">Verify AE rating</a> for why this claim is close to automatic once the AE designation is confirmed.
            </div>
          </div>
        </Field>

        <Field label="Toxic exposure section — fill it in anyway">
          Not the basis for any of these three conditions (all direct or secondary connection, not presumptive), but
          the form asks regardless. List USS Enterprise (CVN-65), 5th Fleet AOR deployment, 2014&ndash;2017,{' '}
          <span className="text-amber-300">[confirm exact port calls/dates in Gulf waters if applicable]</span>. It costs
          nothing and puts a documented exposure history on file for any future PACT-listed condition.
        </Field>

        <Field label="Master checklist &mdash; what's still blank before this is submission-ready">
          <p className="text-xs text-gray-400 mb-1">
            Every bracket above, consolidated. These are the same open items already sitting in the three narrative
            tasks below &mdash; nothing new, just gathered in one place.
          </p>
          <ul className="list-disc list-inside space-y-1">
            <li>Exact date + facility of the in-service INH prescription</li>
            <li>Confirm INH indication (positive PPD / TB prophylaxis)</li>
            <li>Exact date + hospital of the Nissen fundoplication</li>
            <li>Current reflux medication name + dose, and sleep setup</li>
            <li>Nightly reflux-wake frequency and food-stuck/dysphagia frequency</li>
            <li>EGD / barium swallow / dilatation findings (pending GI consult)</li>
            <li>Anxiety treatment status, medication/prescriber if any, panic frequency per week</li>
            <li>Confirm Navy rating = AE on DD-214 line 12 or OMPF cross-training page</li>
            <li>Specific squadron / aircraft / flight-deck duties for the tinnitus narrative</li>
            <li>Onset timing and character (pitch, constant vs. intermittent) of the tinnitus</li>
          </ul>
        </Field>
      </Section>

      <Section id="cp-exams" index={15} title="C&P exams (GI / Mental Health / Audio)" taskId="ptask-fa8a3820c833">
        <Field label="What a C&P exam is">
          Compensation &amp; Pension exam — VA's own medical evaluation of your claimed conditions, done by a
          VA-contracted examiner using a standard checklist called a DBQ (Disability Benefits Questionnaire). Usually
          scheduled 3–8 weeks after your claim is received. You'll have three separate exams (one per condition).
        </Field>
        <Field label="The one rule that matters more than any other">
          Show up. Missing a C&amp;P exam is one of the fastest ways to have a claim denied outright.
        </Field>
        <Field label="How to talk to the examiner">
          Describe your worst day, not your best. If asked "how are you doing," do not say "I'm fine" — that's not
          a formality, examiners record it as a symptom data point. Bring your{' '}
          <a href="#symptom-log" className="text-indigo-400 hover:underline">written symptom log</a> to all three exams.
        </Field>
        <Field label="What to specifically mention per exam">
          <ul className="list-disc list-inside space-y-1">
            <li><span className="text-white">GI (Esophageal Conditions DBQ):</span> daily PPI dose, dysphagia, food impactions, regurgitation, sleep disruption — and name every dilatation by date/provider (this single detail moves the rating 10%→30%→50%)</li>
            <li><span className="text-white">Mental Health DBQ:</span> panic attacks per week (a number, not "sometimes"), sleep disruption hours, social/work impact, no pre-service history</li>
            <li><span className="text-white">Audio/Tinnitus DBQ:</span> sound character, constant vs. intermittent, sleep/concentration impact, and name the specific aircraft/squadron noise exposure</li>
          </ul>
        </Field>
        <Field label="See the actual checklist examiners use">
          <ExternalLink href="https://www.benefits.va.gov/compensation/dbq_publicdbqs.asp">Public DBQ list</ExternalLink> — reading the
          esophageal conditions DBQ ahead of time tells you exactly what the examiner will ask.
        </Field>
      </Section>

      <Section id="symptom-log" index={16} title="Symptom log for the C&P exams" taskId="ptask-3c88e7114e1e">
        <Field label="What this is">
          A one-page-per-condition written log you bring to each C&amp;P exam. Examiners often write down exactly
          what's on the page in front of them, so specificity here directly affects your rating.
        </Field>
        <Field label="GI — the most important one for the rating">
          Nightly reflux frequency, sleep position, how often food gets stuck, foods you can no longer eat, meds
          tried and whether they work, and any prior EGD/barium/dilatation findings (the DC 7206 rating lever).
        </Field>
        <Field label="Anxiety">
          Panic/anxiety frequency per week, sleep interruptions, avoidance behavior around eating/social meals.
        </Field>
        <Field label="Tinnitus">
          Constant vs. intermittent, pitch, loudness relative to a quiet room, sleep-onset delay, and when it
          started relative to your service.
        </Field>
        <p className="text-xs text-gray-500">
          A full fill-in-the-blank template already exists in the board task description — print or screenshot it
          before each exam.
        </p>
      </Section>

      <Section id="narrative-gerd" index={17} title="Narrative — GERD / Hiatal Hernia / Post-Nissen" taskId="ptask-230babb414e2">
        <Field label="What a 'living doc' narrative is">
          A task whose description you keep editing as your memory sharpens and records arrive — every edit is
          captured in the audit trail so nothing is lost. This becomes the master timeline your personal statement,
          buddy statements, and nexus letters all need to match exactly.
        </Field>
        <Field label="What's already drafted">
          Onset aboard USS Enterprise (2014–2017), the in-service INH prescription, the Nissen fundoplication, and
          the permanent residuals (nightly reflux, dysphagia).
        </Field>
        <Field label="What's still marked TODO">
          Exact onset date + INH prescription date, medical facility/provider names, surgery date + hospital,
          current medication + dose, sleep setup, frequency of nightly reflux, frequency of food getting stuck, any
          prior EGD/barium findings, and trigger foods. Fill these in as your STRs and GI consult results arrive.
        </Field>
      </Section>

      <Section id="narrative-anxiety" index={18} title="Narrative — Anxiety secondary to GI chain" taskId="ptask-f11f744679d5">
        <Field label="What's already drafted">
          The mechanism connecting nightly reflux/dysphagia to anxiety around eating and sleeping, plus the legal
          basis for secondary connection (
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.310">38 C.F.R. § 3.310</ExternalLink>).
        </Field>
        <Field label="What's still marked TODO">
          Whether you're currently in treatment (medication/prescriber), quantified frequency of anxiety/panic
          symptoms, how many times reflux wakes you per night, and concrete examples of avoidance (skipping meals
          out, social eating situations, work impact).
        </Field>
      </Section>

      <Section id="narrative-tinnitus" index={19} title="Narrative — Tinnitus (Navy AE noise exposure)" taskId="ptask-70aa714a5f5b">
        <Field label="What's already drafted">
          Service aboard USS Enterprise, the "Highly Probable" noise-exposure designation for AE/aviation ratings,
          and the legal basis (M21-1 continuity-of-symptomatology provisions).
        </Field>
        <Field label="What's still marked TODO">
          Confirm your exact rating/MOS and squadron assignments + dates, the specific aircraft/flight-deck/hangar
          duties, when the ringing started, sound character, and concrete sleep/concentration impacts. Keep this
          consistent with your personal statement — the tinnitus C&amp;P is largely a credibility interview.
        </Field>
      </Section>

      <Section id="rating-tracker" index={20} title="Rating estimate tracker" taskId="ptask-bde76f6b6856">
        <Field label="What this is">
          A running estimate of your combined disability rating across three scenarios (pessimistic / likely /
          strong), using VA's whole-person combined-rating math (
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.25">38 C.F.R. § 4.25</ExternalLink>) — ratings don't simply
          add together.
        </Field>
        <Field label="The likely scenario, worked out">
          GERD 30% + Anxiety 30% + Tinnitus 10% combines to roughly 50%, worth $1,132.90/month (single veteran, no
          dependents, 2026 rate table). The strong scenario (50/50/10) combines to ~70%, worth $1,808.45/month.
        </Field>
        <Field label="Update this as evidence lands">
          Once your EGD results and mental-health treatment records come in, edit this task to reflect which
          scenario you're actually tracking toward.
        </Field>
      </Section>

      <Section id="after-decision" index={21} title="After-decision plan (appeals)" taskId="ptask-bddf73460d9b">
        <Field label="If you're denied or under-rated — don't file a new claim">
          File the correct decision-review form within 1 year of the decision letter instead:
          <ul className="list-disc list-inside space-y-1 mt-1">
            <li><ExternalLink href="https://www.va.gov/find-forms/about-form-20-0995/">Form 20-0995</ExternalLink> — Supplemental Claim (you have new evidence)</li>
            <li><ExternalLink href="https://www.va.gov/find-forms/about-form-20-0996/">Form 20-0996</ExternalLink> — Higher-Level Review (no new evidence; a senior rater re-reviews)</li>
            <li><ExternalLink href="https://www.va.gov/find-forms/about-form-10182/">Form 10182</ExternalLink> — Notice of Disagreement → Board of Veterans' Appeals</li>
          </ul>
          Overview of all three: <ExternalLink href="https://www.va.gov/decision-reviews/">va.gov/decision-reviews</ExternalLink>
        </Field>
        <Field label="This is when a paid attorney makes sense — not before">
          Under <ExternalLink href="https://www.law.cornell.edu/uscode/text/38/5904">38 U.S.C. § 5904</ExternalLink>, attorneys can only
          charge a fee after an initial decision. Reputable veterans-law firms already noted on the board task:
          Chisholm Chisholm &amp; Kilpatrick (CCK), Hill &amp; Ponton, Berry Law, Woods &amp; Woods, Bergmann &amp;
          Moore.
        </Field>
        <Field label="Watch for claim sharks">
          Avoid anyone charging a percentage of back-pay for an initial claim (illegal), guaranteeing a rating
          increase, or requiring an NDA. Always re-verify accreditation at{' '}
          <ExternalLink href="https://www.va.gov/ogc/apps/accreditation/">va.gov accreditation search</ExternalLink> before signing
          anything.
        </Field>
      </Section>
    </div>
    </TaskStatusContext.Provider>
  )
}
