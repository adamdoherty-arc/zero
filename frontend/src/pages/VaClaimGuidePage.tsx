import { createContext, useContext, useEffect, useMemo } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, Circle, ExternalLink as ExternalLinkIcon } from 'lucide-react'
import { usePersonalWorkItems } from '@/hooks/usePersonalWorkItemsApi'
import {
  VA_GUIDE_SECTIONS,
  buildGuideTaskIndex,
  ITF_FILED_DATE,
  ITF_DEADLINE_DATE,
} from '@/config/vaClaimGuide'

/** Section metadata by anchor, so index/title render from config rather than
 *  being restated as JSX literals (which is how section 7's title drifted). */
const SECTION_BY_ANCHOR = new Map(
  VA_GUIDE_SECTIONS.map((s, i) => [s.id, { ...s, index: i + 1 }]),
)

/** Maps guide anchor -> the board task that anchor explains (id + status), so
 *  the guide can show a checkmark and deep-link without threading props
 *  through every Section call. Resolved from the `guide:` tag on each task. */
interface GuideTask {
  id: string
  status: string
}
const GuideTaskContext = createContext<Record<string, GuideTask>>({})

function TaskCheckmark({ anchor }: { anchor: string }) {
  const byAnchor = useContext(GuideTaskContext)
  const done = byAnchor[anchor]?.status === 'done'
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

function BoardLink({ anchor }: { anchor: string }) {
  const byAnchor = useContext(GuideTaskContext)
  const task = byAnchor[anchor]
  // No matching board task (not yet seeded/tagged) — render nothing rather
  // than a link that would deep-link to a task id that doesn't exist.
  if (!task) return null
  const done = task.status === 'done'
  return (
    <Link
      to={`/va-claim?task=${task.id}`}
      className={`inline-flex items-center gap-1.5 text-sm hover:underline ${
        done ? 'text-emerald-400 hover:text-emerald-300' : 'text-indigo-400 hover:text-indigo-300'
      }`}
    >
      <TaskCheckmark anchor={anchor} />
      {done ? 'Done — view on board' : 'Open this task on the board'} →
    </Link>
  )
}

/** Renders index + title from VA_GUIDE_SECTIONS so the config is the only
 *  place a section's number or name is defined. */
function Section({ id, children }: { id: string; children: React.ReactNode }) {
  const meta = SECTION_BY_ANCHOR.get(id)
  return (
    <section id={id} className="glass-card p-6 scroll-mt-20">
      <div className="flex items-start justify-between gap-4 mb-3 flex-wrap">
        <h2 className="text-lg font-semibold text-white">
          <span className="text-gray-500 mr-2">{meta?.index}.</span>
          {meta?.title ?? id}
        </h2>
        <BoardLink anchor={id} />
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
  // anchor -> board task, resolved via each task's `guide:` tag (falling back
  // to the legacy id map for the original seeded tasks).
  const taskByAnchor = useMemo(() => {
    const index = buildGuideTaskIndex(tasks)
    return Object.fromEntries(
      Object.entries(index).map(([anchor, t]) => [
        anchor,
        { id: t.id, status: (t as { status?: string }).status ?? '' },
      ]),
    )
  }, [tasks])
  const doneCount = VA_GUIDE_SECTIONS.filter(
    (s) => taskByAnchor[s.id]?.status === 'done',
  ).length

  // React Router doesn't auto-scroll to a #hash on route entry — do it manually.
  useEffect(() => {
    if (location.hash) {
      const el = document.getElementById(location.hash.slice(1))
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [location.hash])

  return (
    <GuideTaskContext.Provider value={taskByAnchor}>
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
              <TaskCheckmark anchor={s.id} />
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

      <Section id="strategy">
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

      <Section id="intent-to-file">
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
          <span className="text-emerald-400 font-medium">Done.</span> VA <em>received</em> the ITF on{' '}
          <span className="text-white font-medium">{ITF_FILED_DATE}</span> (confirmed 2026-08-03 against the VA.gov
          confirmation email), so the 365-day clock to submit the 21-526EZ runs to{' '}
          <span className="text-white font-medium">{ITF_DEADLINE_DATE}</span>.
          <div className="mt-2 rounded border border-amber-800 bg-amber-950/30 p-3 text-amber-200">
            <strong>Do not use the date this task was ticked (2026-06-20) as the ITF date.</strong> That is 39 days
            later than the real filing date and would overstate your remaining runway. The deadline is{' '}
            {ITF_DEADLINE_DATE}.
          </div>
          <div className="mt-2">
            Filing the 526EZ earlier does not increase back-pay — the effective date is already locked either way.
            But filing earlier <em>does</em> start the C&amp;P exam scheduling clock sooner, and the exam is what
            determines your rating. See{' '}
            <a href="#form-526ez" className="text-indigo-400 hover:underline">section on the 21-526EZ</a> for when to
            actually pull the trigger.
          </div>
        </Field>
        <Field label="Where it lives">
          <ExternalLink href="https://www.va.gov/resources/your-intent-to-file-a-va-claim/">va.gov — Intent to File</ExternalLink> (auto-created
          when you start a 21-526EZ online), or by phone at 1-800-827-1000.
        </Field>
      </Section>

      <Section id="prior-claim-history">
        <Field label="What it is">
          A single yes/no question that has to be answered before anything is submitted: have you ever filed a VA
          disability claim before, at any point since separation, for any condition?
        </Field>
        <Field label="Why it matters">
          It changes which instrument you file. If you have never filed, the 21-526EZ is an original claim and
          everything proceeds as planned. If you filed before and were <em>denied</em>, filing a brand-new claim on
          that same condition is the wrong move &mdash; the correct path is a Supplemental Claim (20-0995) or a
          Higher-Level Review (20-0996), and filing new can forfeit the earlier effective date. The effective date is
          where the back pay lives, so this is not a technicality.
        </Field>
        <Field label="Where to check">
          <ExternalLink href="https://www.va.gov/track-claims/">va.gov/track-claims</ExternalLink> shows claim status and history. Your CVSO can pull the file directly at the 21-22
          appointment, and the full C-file request (see below) is the exhaustive answer.
        </Field>
        <Field label="Signal worth taking seriously">
          A claim-shark outfit emailing to ask for &ldquo;past rating decision letters&rdquo; implies they believe
          there is history. Resolve this before submitting anything.
        </Field>
      </Section>

      <Section id="digital-accounts">
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

      <Section id="ompf-strs">
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

      <Section id="scan-str">
        <Field label="The situation">
          You hold the <span className="text-white font-medium">original</span> service treatment record. That is
          almost certainly why the NPRC request came back empty &mdash; the file was released to you at separation,
          so there is no copy left in St. Louis to find.
        </Field>
        <div className="rounded-lg border border-rose-800 bg-rose-950/30 text-rose-200 px-4 py-3 text-sm">
          <span className="font-semibold text-rose-100">Never mail the original to VA.</span> Records mailed in
          routinely do not come back, and there is no second original. Submit scans only. If VA ever demands a
          certified copy, your CVSO can certify against the original &mdash; you still never surrender it.
        </div>
        <Field label="How to scan it properly">
          Every page, both sides, in page order, 300 dpi minimum. A phone scanning app is fine if the text is fully
          legible. Save as one combined PDF, keep a backup somewhere off the machine, and store the paper original
          somewhere fireproof and dry.
        </Field>
        <Field label="What to look for as you scan">
          The isoniazid (INH) prescription &mdash; date, prescriber, and the reason it was given. Any hiatal hernia
          workup (upper GI series, EGD, manometry). Every sick-call entry for stomach, reflux, headache, or hearing
          complaints. The operative report, if it happens to be in there. Record the page number of each so you can
          cite them later.
        </Field>
      </Section>

      <Section id="operative-report">
        <Field label="Why the first request failed">
          Per NARA, NPRC files inpatient and clinical records by the <span className="text-white font-medium">name
          of the hospitalizing facility and the year of treatment</span> &mdash; not by veteran name. A request
          submitted under your name searches personnel and outpatient files only, so an inpatient surgical record can
          never surface. That is exactly what happened to case C-0007768198.
        </Field>
        <Field label="Why it is worth re-requesting">
          The Nissen fundoplication operative report is the single most important document in the GI claim. It
          establishes the in-service surgical event that the entire direct-service-connection theory rests on.
        </Field>
        <Field label="How to request it correctly">
          Submit a new request giving the <span className="text-white font-medium">name and location of the
          hospitalizing facility</span> and the <span className="text-white font-medium">year of treatment</span>.
          Without those two fields the search cannot run. Use <ExternalLink href="https://www.archives.gov/veterans/military-service-records">NARA SF-180</ExternalLink> or the eVetRecs online path.
        </Field>
        <Field label="If you do not know the facility name">
          It will be in the STR you are scanning &mdash; look for the pre-op clearance or the referral note. This is
          why the scan task comes first.
        </Field>
      </Section>

      <Section id="nmra-backstop">
        <Field label="What it is">
          Navy Medicine Records Activity (NMRA), the BUMED detachment that holds Navy health records. A parallel
          request here is belt-and-braces: even holding the original, a VA-sourced copy closes any argument that the
          file is incomplete, and NMRA may hold material that never made it into the copy released at separation.
        </Field>
        <Field label="Where to send it (separation on or after 1 Jan 2014)">
          Navy Medicine Records Activity, BUMED Detachment<br />
          1222 Spruce Street, Room 9.308, Saint Louis, MO 63103<br />
          Email: usn.ncr.bumedfchva.mbx.nmra-roi@health.mil &middot; Release of Information: 667-892-3443
        </Field>
        <Field label="Which form">
          <ExternalLink href="https://www.archives.gov/veterans/military-service-records">NARA SF-180</ExternalLink> or DD Form 2870 (November 2023 version). Releasing to a third party additionally requires
          DD Form 3130. For a separation between 31 Jan 1994 and 31 Dec 2013 the NPRC letter instead directs you to
          the VA Records Management Center.
        </Field>
      </Section>

      <Section id="cvso-str-check">
        <Field label="Possibly the fastest route of all, and it costs one question">
          The NPRC letter states that if a VA claim was filed, the service member health record may already have
          been sent to the VA Regional Office serving the veteran. VA also routinely pulls STRs itself once a claim
          is filed. Your Intent to File went in on <span className="text-white font-medium">12 May 2026</span>, so VA
          may already have requested and received the file.
        </Field>
        <Field label="What to ask">
          At the Duval CVSO appointment (904-255-5550), ask them to check directly whether the STRs are already in
          the VA system. If they are, the entire records chase collapses to nothing and the claim moves straight to
          the nexus letter and the EGD. VA general line for the same question: 1-800-827-1000.
        </Field>
        <Field label="Do this before the other records tasks">
          It is one phone call and it can make three other tasks unnecessary.
        </Field>
      </Section>

      <Section id="c-file">
        <Field label="What it is">
          The C-file is everything VA holds on you. It is separate from the NPRC service records. If any prior
          claim, rating, or VA correspondence exists, it is in there &mdash; which also answers the{' '}
          <a href="#prior-claim-history" className="text-indigo-400 hover:underline">prior claim history</a> question
          definitively.
        </Field>
        <Field label="How to request">
          Fastest is the FOIA/Privacy Act request online through VA.gov. Otherwise VA Form 20-10206, mailed to
          Department of Veterans Affairs, Evidence Intake Center, PO Box 4444, Janesville, WI 53547-4444, or faxed to
          (844) 531-7818.
        </Field>
        <div className="rounded-lg border border-amber-800 bg-amber-950/30 text-amber-200 px-4 py-3 text-sm">
          <span className="font-semibold text-amber-100">The form requires a wet signature.</span> A typed signature
          is rejected. And the mail timeline is <span className="text-white">5 to 8 months</span> &mdash; file it now
          and let it run in the background. Requesting only specific documents rather than the entire file is faster.
        </div>
        <Field label="Shortcut">
          Your CVSO can often pull the file directly at the 21-22 appointment, which is dramatically faster than the
          mail path.
        </Field>
      </Section>

      <Section id="form-4142">
        <Field label="What it is">
          VA Form 21-4142 plus 21-4142a authorizes VA to request medical records directly from{' '}
          <span className="text-white font-medium">private</span> providers on your behalf.
        </Field>
        <Field label="Why it matters">
          Without it you are personally chasing every private record. Filing 4142 makes VA do the chasing, and it
          closes gaps you do not know exist. It is a standard component of a complete claim and costs nothing to
          include.
        </Field>
        <Field label="Who to list on it">
          Every private provider: the gastroenterologist, the PCP, the anxiety prescriber, the neurologist or
          whoever treats the headaches, the dentist if pursuing dental erosion, and any urgent care or ER visited for
          reflux or a food impaction.
        </Field>
        <Field label="Where to get it">
          <ExternalLink href="https://www.va.gov/find-forms/about-form-21-4142/">va.gov — about Form 21-4142</ExternalLink>. Submit it with the 21-526EZ, or earlier through the CVSO.
        </Field>
      </Section>

      <Section id="va-health-care">
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

      <Section id="cvso-poa">
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

      <Section id="gi-consult">
        <Field label="Why this one task matters more than any other">
          Your GERD claim is rated under Diagnostic Code 7206 (rewritten May 19, 2024), which grades you on
          documented findings, not on how bad symptoms feel. Without an EGD on record, a rater has nothing to point
          to except "takes a daily PPI" — which caps you at 10%.
        </Field>
        <Field label="The DC 7206 rating ladder">
          <ul className="list-disc list-inside space-y-1">
            <li><span className="text-white">0%</span> — documented history without daily symptoms or daily medication</li>
            <li><span className="text-white">10%</span> — stricture requiring daily medication to control dysphagia, otherwise asymptomatic</li>
            <li><span className="text-white">30%</span> — recurrent stricture requiring dilatation <span className="text-white font-medium">no more than 2 times per year</span></li>
            <li><span className="text-white">50%</span> — recurrent or refractory stricture requiring dilatation <span className="text-white font-medium">3 or more times per year</span>, OR steroid-assisted dilatation at least once a year, OR stent placement</li>
            <li><span className="text-white">80%</span> — recurrent or refractory stricture causing dysphagia with aspiration, undernutrition, and/or substantial weight loss, plus surgical correction or a PEG tube</li>
          </ul>
          <div className="mt-2 rounded border border-rose-800 bg-rose-950/30 p-3 text-rose-200">
            <span className="font-semibold text-rose-100">Corrected 2026-08-03 — the earlier version of this ladder
            had 30% and 50% swapped.</span> The direction that matters:{' '}
            <span className="text-white font-medium">more frequent dilatation supports a HIGHER rating, not a lower
            one.</span> Every dilatation, every steroid-assisted procedure, and every food impaction requiring
            intervention must be in the record with a date. Do not under-report frequency at the C&amp;P exam.
            Verified against <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.114">38 C.F.R. § 4.114</ExternalLink> (DC 7206 rates by reference to DC 7203).
          </div>
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

      <Section id="impaction-log">
        <Field label="Why this is the highest-value unrecorded evidence you have">
          You report near-daily painful swallowing and frequent, painful food impactions &mdash; and none of it
          exists in any medical record. Under DC 7206, dysphagia severity and dilatation frequency are exactly what
          separate 10% from 30% from 50%. Symptoms nobody wrote down did not happen, as far as a rater is concerned.
        </Field>
        <Field label="One line per episode">
          Date and approximate time &middot; what food &middot; how long it was stuck &middot; what resolved it
          (water, waiting, regurgitating, a clinic or ER visit) &middot; pain level 1&ndash;10 &middot; whether
          anyone witnessed it.
        </Field>
        <div className="rounded-lg border border-amber-800 bg-amber-950/30 text-amber-200 px-4 py-3 text-sm">
          <span className="font-semibold text-amber-100">Any episode severe enough to consider going in &mdash; go
          in.</span> An ER or urgent-care record documenting an impaction is worth more to this claim than a hundred
          lines of self-report, and if it results in a dilatation it moves the rating bracket directly.
        </div>
        <Field label="Where it goes">
          Bring it to the GI consult and to the GI C&amp;P exam. It also feeds the{' '}
          <a href="#symptom-log" className="text-indigo-400 hover:underline">C&amp;P symptom log</a>.
        </Field>
      </Section>

      <Section id="weight-log">
        <Field label="Why start now">
          The 80% level under DC 7206 turns on aspiration, undernutrition, or{' '}
          <span className="text-white font-medium">substantial weight loss</span> &mdash; and nobody is recording
          weight. There is no way to prove a downward trend later without a baseline started now. This is a
          two-minute-per-month task that is the only thing capable of supporting the top bracket or a future
          increase.
        </Field>
        <Field label="Record on the first of each month">
          Weight &middot; nights per week woken by reflux &middot; painful-swallow episodes per week &middot; food
          impactions that month &middot; panic episodes per week &middot; current medications and doses.
        </Field>
        <Field label="Double duty">
          This is the source data for the C&amp;P symptom log, so keeping it saves work later rather than adding it.
        </Field>
      </Section>

      <Section id="headache-log">
        <Field label="Why it exists">
          Migraines are rated almost entirely on the frequency of <em>prostrating</em> attacks under 38 C.F.R.
          &sect; 4.124a, DC 8100 &mdash; and that record can only be built forward in time. Starting it late is the
          one thing here that cannot be recovered.
        </Field>
        <Field label="The rating ladder">
          <span className="text-white">10%</span> &mdash; prostrating attacks averaging one in 2 months over the last
          several months. <span className="text-white">30%</span> &mdash; prostrating attacks averaging{' '}
          <span className="text-white font-medium">once a month</span>. <span className="text-white">50%</span>{' '}
          &mdash; very frequent, completely prostrating and prolonged attacks productive of severe economic
          inadaptability.
        </Field>
        <div className="rounded-lg border border-amber-800 bg-amber-950/30 text-amber-200 px-4 py-3 text-sm">
          <span className="font-semibold text-amber-100">&ldquo;Prostrating&rdquo; is the whole ballgame.</span> It
          means the attack forces you to stop what you are doing and lie down in a dark, quiet room. A headache you
          power through does not count. Answer that question explicitly in every log entry.
        </div>
        <Field label="One line per headache">
          Date and start time &middot; duration &middot; did you have to stop and lie down &middot; light/sound
          sensitivity, nausea, vomiting, aura &middot; medication taken and whether it worked &middot; work impact
          (late, left early, missed the day).
        </Field>
        <Field label="Get them treated, not just logged">
          A private log alone is weak. A PCP or neurology note reading &ldquo;reports 3&ndash;4 prostrating migraines
          per month&rdquo; is worth far more &mdash; and the log is what produces that sentence at the appointment.
          See <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.124a">38 C.F.R. § 4.124a (DC 8100)</ExternalLink>.
        </Field>
      </Section>

      <Section id="surgery-inventory">
        <Field label="Why this is potentially the biggest untapped item on the board">
          You report that <span className="text-white font-medium">every surgery you have ever had was performed
          while in the Navy</span>. The original playbook only tracked the Nissen fundoplication. Any other
          in-service surgery is potentially its own service-connected condition with its own rating, and none of them
          are currently claimed.
        </Field>
        <Field label="Build the table as soon as the records are readable">
          One row per surgery: surgery &middot; date &middot; facility &middot; surgeon &middot; residuals today.
        </Field>
        <Field label="Ask three questions of every surgery found">
          1. Does it still cause symptoms, pain, limited motion, scarring, or numbness today? 2. Is there a surgical
          scar? Scars are separately ratable &mdash; see{' '}
          <a href="#surgical-scars" className="text-indigo-400 hover:underline">surgical scars</a>. 3. Did it lead to
          anything downstream (adhesions, hernia, chronic pain, nerve damage)? Anything answering yes gets added to
          the claim.
        </Field>
      </Section>

      <Section id="surgical-scars">
        <Field label="Commonly missed, easy to claim">
          You have at minimum the laparoscopic port scars from the Nissen fundoplication, plus whatever else the
          records show. Scars are one of the most frequently overlooked ratings.
        </Field>
        <Field label="How they rate under 38 C.F.R. 4.118">
          Painful scars rate under DC 7804: <span className="text-white">one or two</span> painful scars is 10%,{' '}
          <span className="text-white">three or four</span> is 20%, <span className="text-white">five or more</span>{' '}
          is 30%. Unstable scars (frequent loss of skin covering) rate higher. Deep, non-linear scars rate by area
          under DC 7801. Full text: <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.118">38 C.F.R. § 4.118</ExternalLink>.
        </Field>
        <Field label="What to do">
          Photograph every surgical scar with a ruler for scale, note whether each is painful to the touch, and list
          them as claimed conditions on the 21-526EZ. Mention them at the C&amp;P exam &mdash; an examiner will not
          evaluate a scar that was never claimed.
        </Field>
      </Section>

      <Section id="dental-erosion">
        <Field label="Low value on its own, but cheap and corroborating">
          Chronic acid reflux erodes tooth enamel. A dentist noting acid erosion does two things: it opens a small
          secondary claim, and &mdash; more usefully &mdash; it is objective third-party corroboration that the
          reflux is severe and long-standing, which supports the primary GI rating.
        </Field>
        <Field label="What to do">
          At the next dental visit, ask the dentist to note any acid erosion in the chart explicitly, and request a
          copy. That is the whole task.
        </Field>
      </Section>

      <Section id="hearing-loss">
        <Field label="Why it belongs in this claim">
          Tinnitus is capped at a flat 10% under DC 6260 &mdash; that is the ceiling no matter how severe it is.
          Hearing loss is a <span className="text-white font-medium">separate</span> rating under DC 6100, and it
          rides on the exact same in-service noise-exposure concession already granted to carrier aviation ratings
          under VBA Fast Letter 10-35.
        </Field>
        <Field label="What it costs you">
          Almost nothing. The audiologist performs the audiogram at the Audio C&amp;P exam anyway. The only
          requirement is that hearing loss be <span className="text-white font-medium">listed as a claimed
          condition</span> on the 21-526EZ so the examiner evaluates it and the rater adjudicates it.
        </Field>
        <Field label="Set expectations honestly">
          VA hearing loss must first qualify as a disability under <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/3.385">38 C.F.R. § 3.385</ExternalLink>: an auditory threshold of 40 dB or
          greater at 500, 1000, 2000, 3000, or 4000 Hz; or 26 dB or greater at three of those frequencies; or
          Maryland CNC speech recognition under 94%. Many veterans rate 0%. A 0% rating is still worth having &mdash;
          it establishes service connection, which makes any future worsening a simple increase rather than a fresh
          claim.
        </Field>
        <Field label="Action">
          Add &ldquo;bilateral hearing loss&rdquo; to the conditions claimed on the 21-526EZ and request an audiogram
          at the C&amp;P. Draft the story in{' '}
          <a href="#narrative-hearing-loss" className="text-indigo-400 hover:underline">the hearing loss narrative</a>.
        </Field>
      </Section>

      <Section id="migraines">
        <Field label="Missing from the original playbook entirely">
          And it is one of the higher-value conditions available. Migraines rate 0 / 10 / 30 / 50% under DC 8100. A
          30% rating is realistic with a documented average of one prostrating attack per month &mdash; the same
          bracket as the GI condition and anxiety. In combined-rating math that is not a rounding error.
        </Field>
        <Field label="Three things have to be true">
          <span className="text-white">1. A current diagnosis.</span> See a PCP or neurologist and get
          &ldquo;migraine&rdquo; (or &ldquo;headache disorder&rdquo;) written in the chart &mdash; without a
          diagnosis there is nothing to rate. <span className="text-white">2. A documented frequency of prostrating
          attacks</span> &mdash; that is what the{' '}
          <a href="#headache-log" className="text-indigo-400 hover:underline">headache log</a> produces.{' '}
          <span className="text-white">3. A service-connection theory</span> &mdash; direct (onset in service,
          &sect; 3.303) or secondary to an already-claimed condition (&sect; 3.310).
        </Field>
        <div className="rounded-lg border border-rose-800 bg-rose-950/30 text-rose-200 px-4 py-3 text-sm">
          If claiming migraines as <em>secondary</em>, name the primary condition in exactly the same wording used to
          list that primary elsewhere on the form. A wording mismatch between the primary and the secondary is a
          common and entirely avoidable own-goal.
        </div>
        <Field label="Action">
          List &ldquo;migraine headaches&rdquo; as a claimed condition on the 21-526EZ and request a neurology
          C&amp;P exam (Headaches DBQ). Bring the headache log. Work out which theory the evidence supports in{' '}
          <a href="#narrative-migraines" className="text-indigo-400 hover:underline">the migraine narrative</a>.
        </Field>
      </Section>

      <Section id="buddy-statements">
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

      <Section id="personal-statement">
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

      <Section id="evidence-packet">
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

      <Section id="gi-nexus">
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

      <Section id="anxiety-nexus">
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

      <Section id="ae-rating">
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

      <Section id="form-526ez">
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
        <Field label="FDC vs Standard — the honest math">
          The Fully Developed Claim lane is worth far less than it sounds. VA's own numbers: FDC averages ~75.7 days,
          Standard averages ~78.6 days. That is a <span className="text-white font-medium">~3-day</span> advantage.
          And per{' '}
          <ExternalLink href="https://www.va.gov/disability/how-to-file-claim/evidence-needed/fully-developed-claims/">VA's FDC program page</ExternalLink>,
          submitting <em>any</em> additional evidence after an FDC removes the claim from the FDC program and reverts
          it to Standard anyway — so the moment your EGD report arrives, the lane is forfeited regardless.
          <div className="mt-2">
            The genuinely useful rule: you can keep uploading evidence for <span className="text-white font-medium">1 year</span>{' '}
            from the date VA receives the claim. That is the window the plan below exploits. A Decision Ready Claim
            through a VSO is still worth asking about — that one really can land under 30 days.
          </div>
        </Field>
        <Field label="What to attach">
          The medical evidence packet, GI nexus letter, anxiety nexus paragraph, buddy statements, personal
          statement, and your DD-214. Claim <span className="text-white font-medium">every</span> condition in one
          submission — GERD chain, anxiety (secondary), tinnitus,{' '}
          <a href="#hearing-loss" className="text-indigo-400 hover:underline">bilateral hearing loss</a>,{' '}
          <a href="#migraines" className="text-indigo-400 hover:underline">migraines</a>, and any{' '}
          <a href="#surgical-scars" className="text-indigo-400 hover:underline">surgical scars</a>. A condition you
          do not list is a condition no examiner evaluates and no rater adjudicates.
        </Field>
        <Field label="The deadline that actually matters">
          Must be submitted within 365 days of your Intent to File —{' '}
          <span className="text-white font-medium">{ITF_DEADLINE_DATE}</span> — to keep the back-dated effective
          date. See <a href="#intent-to-file" className="text-indigo-400 hover:underline">Intent to File</a>.
        </Field>
        <Field label="After you submit">
          Track status at <ExternalLink href="https://www.va.gov/track-claims/">va.gov/track-claims</ExternalLink>. Get a confirmation
          receipt with your claim number from the CVSO.
        </Field>

        <div className="rounded-lg border border-emerald-800 bg-emerald-950/30 text-emerald-200 px-4 py-3 text-sm">
          <span className="font-semibold text-emerald-100">
            File as soon as the EGD is <em>scheduled</em> — not once it is completed.
          </span>
          <div className="mt-2">
            The old guidance here said &ldquo;don&apos;t file yet, wait for the EGD.&rdquo; That costs two to three
            months for no benefit. Here is why:
          </div>
          <ul className="mt-2 space-y-1 list-disc list-inside">
            <li>
              C&amp;P exams are scheduled <span className="text-white">3&ndash;8 weeks after filing</span> — a window
              wide enough for the EGD to land inside it and still reach the rater.
            </li>
            <li>
              Evidence can be uploaded for <span className="text-white">1 year</span> after VA receives the claim, so
              filing early forfeits nothing.
            </li>
            <li>
              GERD floors at 10% on continuous-medication evidence alone under DC 7206, so the EGD is pure upside
              (10% &rarr; 30% &rarr; 50%), never a prerequisite.
            </li>
          </ul>
          <div className="mt-2">
            <span className="font-semibold text-emerald-100">The gate:</span> once an EGD appointment exists on the
            calendar, file. Then upload the report the day it arrives. See{' '}
            <a href="#gi-consult" className="underline hover:text-emerald-100">GI consult / EGD</a>.
          </div>
          <div className="mt-2 text-emerald-300/80">
            Runway to the {ITF_DEADLINE_DATE} deadline is roughly 9 months — comfortable, but the C&amp;P exam is the
            thing worth racing, not the deadline.
          </div>
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

      <Section id="cp-exams">
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

      <Section id="symptom-log">
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

      <Section id="narrative-gerd">
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

      <Section id="narrative-anxiety">
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

      <Section id="narrative-tinnitus">
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

      <Section id="narrative-hearing-loss">
        <Field label="What this is">
          A living document, same as the other narratives. The description on the board task <em>is</em> the
          narrative &mdash; edit it as memory and records sharpen, and every save creates an audit-trail event
          showing how it evolved.
        </Field>
        <Field label="What is drafted">
          The AE duty description, flight-line and hangar-deck noise exposure, the inadequacy of hearing protection
          in specific situations, and present-day difficulty following conversation in background noise.
        </Field>
        <Field label="Still to fill in">
          Specific ship and squadron names with dates &middot; aircraft types &middot; concrete situations where
          hearing protection was inadequate or impractical &middot; onset timeline &middot; specific present-day
          examples (restaurants, phone, television volume, asking people to repeat) &middot; whether family have
          remarked on it.
        </Field>
        <Field label="Why the specifics matter">
          &ldquo;I have trouble hearing&rdquo; is worth little. &ldquo;I cannot follow a conversation in a
          restaurant and my wife has to repeat herself from the next room&rdquo; is what an examiner writes down.
        </Field>
      </Section>

      <Section id="narrative-migraines">
        <Field label="What this is">
          A living document. Edit the board task description over time; each save is captured in the audit trail.
        </Field>
        <Field label="What is drafted">
          Onset framing, symptom character, the prostrating-attack description, frequency, treatment status, and work
          impact &mdash; plus the three candidate service-connection theories to choose between.
        </Field>
        <Field label="Pick the theory the records actually support">
          <span className="text-white">Direct</span> &mdash; headaches began in service and continued since
          (&sect; 3.303); strongest if the STR shows any sick-call entry for headaches, so check while scanning.{' '}
          <span className="text-white">Secondary</span> &mdash; proximately due to or aggravated by an
          already-claimed condition (&sect; 3.310); anxiety and chronic sleep disruption are both recognized headache
          drivers. <span className="text-white">Aggravation</span> &mdash; pre-existing headaches made permanently
          worse by service.
        </Field>
        <Field label="Still to fill in">
          Onset timeline and any in-service sick-call entry &middot; frequency and duration &middot; whether attacks
          are prostrating and how often &middot; current treatment and prescriber &middot; documented work impact
          &middot; which theory the evidence supports.
        </Field>
      </Section>

      <Section id="rating-tracker">
        <Field label="What this is">
          A running estimate of your combined disability rating across three scenarios, using VA's whole-person
          combined-rating math (
          <ExternalLink href="https://www.law.cornell.edu/cfr/text/38/4.25">38 C.F.R. § 4.25</ExternalLink>) — ratings don't simply
          add together.
        </Field>
        <div className="rounded border border-rose-800 bg-rose-950/30 p-3 text-rose-200 text-sm">
          <span className="font-semibold text-rose-100">Corrected 2026-08-03.</span> The rating is{' '}
          <span className="text-white font-medium">100 minus remaining efficiency</span>, rounded to the nearest 10
          once, at the very end. The earlier version reported remaining efficiency as if it were the rating, which
          understated every scenario by a full bracket.
        </div>
        <Field label="Scenarios (single veteran, no dependents, 2026 rate table)">
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left mt-1">
              <thead className="text-xs uppercase tracking-wider text-gray-500 border-b border-gray-800">
                <tr>
                  <th className="py-2 pr-3">Scenario</th>
                  <th className="py-2 pr-3">GERD</th>
                  <th className="py-2 pr-3">Anxiety</th>
                  <th className="py-2 pr-3">Migraine</th>
                  <th className="py-2 pr-3">Tinnitus</th>
                  <th className="py-2 pr-3">Hearing</th>
                  <th className="py-2 pr-3">Scars</th>
                  <th className="py-2 pr-3">Combined</th>
                  <th className="py-2">Monthly</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                <tr>
                  <td className="py-2 pr-3">Conservative</td>
                  <td className="py-2 pr-3">10%</td><td className="py-2 pr-3">30%</td><td className="py-2 pr-3">0%</td>
                  <td className="py-2 pr-3">10%</td><td className="py-2 pr-3">0%</td><td className="py-2 pr-3">0%</td>
                  <td className="py-2 pr-3 text-white font-medium">40%</td><td className="py-2">$795.84</td>
                </tr>
                <tr className="bg-indigo-950/20">
                  <td className="py-2 pr-3 text-white font-medium">Likely</td>
                  <td className="py-2 pr-3">30%</td><td className="py-2 pr-3">30%</td><td className="py-2 pr-3">30%</td>
                  <td className="py-2 pr-3">10%</td><td className="py-2 pr-3">0%</td><td className="py-2 pr-3">10%</td>
                  <td className="py-2 pr-3 text-white font-medium">70%</td>
                  <td className="py-2 text-white font-medium">$1,808.45</td>
                </tr>
                <tr>
                  <td className="py-2 pr-3">Strong</td>
                  <td className="py-2 pr-3">50%</td><td className="py-2 pr-3">50%</td><td className="py-2 pr-3">30%</td>
                  <td className="py-2 pr-3">10%</td><td className="py-2 pr-3">10%</td><td className="py-2 pr-3">10%</td>
                  <td className="py-2 pr-3 text-white font-medium">90%</td><td className="py-2">$2,362.30</td>
                </tr>
              </tbody>
            </table>
          </div>
        </Field>
        <Field label="Worked example — the Likely row">
          Largest first: 30, 30, 30, 10, 10. → 30% leaves 70 efficient → 30% of 70 = 21, leaves 49 → 30% of 49 =
          14.7, leaves 34.3 → 10% of 34.3 = 3.43, leaves 30.87 → 10% of 30.87 = 3.09, leaves 27.78. Combined ={' '}
          100 − 27.78 = 72.2 → rounds to <span className="text-white font-medium">70%</span>.
        </Field>
        <Field label="What the added conditions are worth">
          The original three-condition claim (GERD + anxiety + tinnitus) tops out at 60% Likely / 80% Strong. Adding{' '}
          <a href="#migraines" className="text-indigo-400 hover:underline">migraines</a> and{' '}
          <a href="#surgical-scars" className="text-indigo-400 hover:underline">surgical scars</a> moves Likely to
          70% — $1,435.02 → $1,808.45, about <span className="text-white font-medium">$373/month</span>.{' '}
          <a href="#hearing-loss" className="text-indigo-400 hover:underline">Hearing loss</a> frequently rates 0%,
          but a 0% rating still establishes service connection, which turns any future worsening into a simple
          increase rather than a fresh claim.
        </Field>
        <Field label="Update this as evidence lands">
          Once your EGD results, headache log, and mental-health treatment records come in, edit the board task to
          reflect which scenario you're actually tracking toward. These are estimates, not promises — the rater
          decides.
        </Field>
      </Section>

      <Section id="after-decision">
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
    </GuideTaskContext.Provider>
  )
}
