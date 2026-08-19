/**
 * Maps VA Claim board tasks to their explainer section in VaClaimGuidePage.
 * Single source of truth so the board (task cards + detail dialog) and the
 * guide page ("Learn more" / "Open on board" links) never drift apart.
 *
 * The join is by a `guide:<anchor>` TAG on the task, not by task id. Task ids
 * are generated at seed time, so an id-based join silently orphans every
 * mapping whenever the board is re-seeded into a fresh database — and it means
 * any task added after the original seed has no guide entry at all (which is
 * how 13 tasks ended up unmapped). `taskIds` is retained purely as a fallback
 * for the original 21 seeded tasks that predate the tag convention.
 */
export interface VaGuideSection {
  /** Anchor slug used as the section id + URL hash (/va-claim/guide#id). */
  id: string
  title: string
  /** Legacy fallback: board task ids from the original 2026-05-12 seed. */
  taskIds: string[]
}

/** Tag prefix that binds a board task to a guide section. */
export const GUIDE_TAG_PREFIX = 'guide:'

export const VA_GUIDE_SECTIONS: VaGuideSection[] = [
  { id: 'strategy', title: 'Overall strategy (TL;DR)', taskIds: ['ptask-b4d69d8ed04c'] },
  { id: 'intent-to-file', title: 'Intent to File — VA Form 21-0966', taskIds: ['ptask-6d5818a69ce4'] },
  { id: 'prior-claim-history', title: 'Confirm prior claim history before filing', taskIds: [] },
  { id: 'digital-accounts', title: 'Digital accounts (VA.gov, MyHealtheVet, milConnect, eVetRecs)', taskIds: ['ptask-fb6be90fa7cc'] },
  { id: 'ompf-strs', title: 'OMPF + Service Treatment Records', taskIds: ['ptask-ea9e75a0210a'] },
  { id: 'scan-str', title: 'Scan the original STR — never mail it', taskIds: [] },
  { id: 'operative-report', title: 'Re-request the operative report by hospital name', taskIds: [] },
  { id: 'nmra-backstop', title: 'NMRA records backstop', taskIds: [] },
  { id: 'cvso-str-check', title: 'Ask the CVSO whether VA already holds the STRs', taskIds: [] },
  { id: 'c-file', title: 'Request the full C-file — VA Form 20-10206', taskIds: [] },
  { id: 'form-4142', title: 'Private-records authorization — VA Form 21-4142', taskIds: [] },
  { id: 'va-health-care', title: 'VA health care enrollment', taskIds: ['ptask-f94d26c40b2f'] },
  { id: 'cvso-poa', title: 'CVSO / DAV appointment + Power of Attorney — VA Form 21-22', taskIds: ['ptask-48def01570b4'] },
  { id: 'gi-consult', title: 'GI consult + EGD / barium swallow', taskIds: ['ptask-c2fa773ea065'] },
  { id: 'impaction-log', title: 'Food-impaction and painful-swallow log', taskIds: [] },
  { id: 'weight-log', title: 'Monthly weight and symptom-frequency log', taskIds: [] },
  { id: 'headache-log', title: 'Daily headache log', taskIds: [] },
  { id: 'surgery-inventory', title: 'Inventory every in-service surgery', taskIds: [] },
  { id: 'surgical-scars', title: 'Surgical scars as separate ratings', taskIds: [] },
  { id: 'dental-erosion', title: 'Dental erosion as a GERD secondary', taskIds: [] },
  { id: 'hearing-loss', title: 'Bilateral hearing loss alongside tinnitus', taskIds: [] },
  { id: 'migraines', title: 'Migraine headaches', taskIds: [] },
  { id: 'buddy-statements', title: 'Buddy statements — VA Form 21-10210', taskIds: ['ptask-6fad49e1fca7'] },
  { id: 'personal-statement', title: 'Personal statement — VA Form 21-4138', taskIds: ['ptask-7ce2d37358e7'] },
  { id: 'evidence-packet', title: 'Medical evidence packet', taskIds: ['ptask-52b5b8765666'] },
  { id: 'gi-nexus', title: 'GI nexus letter', taskIds: ['ptask-2811de903469'] },
  { id: 'anxiety-nexus', title: 'Anxiety nexus paragraph', taskIds: ['ptask-3d6fa0d5fa47'] },
  { id: 'ae-rating', title: 'Verify AE rating (tinnitus)', taskIds: ['ptask-55bcda074240'] },
  { id: 'form-526ez', title: 'Submit VA Form 21-526EZ — the main claim', taskIds: ['ptask-13453b116577'] },
  { id: 'cp-exams', title: 'C&P exams (GI / Mental Health / Audio / Neuro)', taskIds: ['ptask-fa8a3820c833'] },
  { id: 'symptom-log', title: 'Symptom log for the C&P exams', taskIds: ['ptask-3c88e7114e1e'] },
  { id: 'narrative-gerd', title: 'Narrative — GERD / Hiatal Hernia / Post-Nissen', taskIds: ['ptask-230babb414e2'] },
  { id: 'narrative-anxiety', title: 'Narrative — Anxiety secondary to GI chain', taskIds: ['ptask-f11f744679d5'] },
  { id: 'narrative-tinnitus', title: 'Narrative — Tinnitus', taskIds: ['ptask-70aa714a5f5b'] },
  { id: 'narrative-hearing-loss', title: 'Narrative — Bilateral hearing loss', taskIds: [] },
  { id: 'narrative-migraines', title: 'Narrative — Migraine headaches', taskIds: [] },
  { id: 'rating-tracker', title: 'Rating estimate tracker', taskIds: ['ptask-bde76f6b6856'] },
  { id: 'after-decision', title: 'After-decision plan (appeals)', taskIds: ['ptask-bddf73460d9b'] },
]

/** Valid anchors, for validating a `guide:` tag before trusting it. */
const KNOWN_ANCHORS = new Set(VA_GUIDE_SECTIONS.map((s) => s.id))

/** Legacy id → anchor fallback for the original seeded tasks. */
const TASK_ID_TO_ANCHOR: Record<string, string> = VA_GUIDE_SECTIONS.reduce(
  (acc, section) => {
    for (const taskId of section.taskIds) acc[taskId] = section.id
    return acc
  },
  {} as Record<string, string>,
)

/** Minimal shape needed to resolve a guide anchor. */
export interface GuideLinkableTask {
  id: string
  tags?: string[] | null
}

/**
 * Resolve the guide anchor for a board task: `guide:<anchor>` tag first, then
 * the legacy hardcoded id map. Returns undefined when the task has no section.
 */
export function getGuideAnchorForTask(task: GuideLinkableTask | string): string | undefined {
  if (typeof task === 'string') return TASK_ID_TO_ANCHOR[task]

  for (const tag of task.tags ?? []) {
    if (!tag.startsWith(GUIDE_TAG_PREFIX)) continue
    const anchor = tag.slice(GUIDE_TAG_PREFIX.length)
    if (KNOWN_ANCHORS.has(anchor)) return anchor
  }
  return TASK_ID_TO_ANCHOR[task.id]
}

/** Build anchor → task map for the guide page (checkmarks + board deep links). */
export function buildGuideTaskIndex(
  tasks: GuideLinkableTask[],
): Record<string, GuideLinkableTask> {
  const index: Record<string, GuideLinkableTask> = {}
  for (const task of tasks) {
    const anchor = getGuideAnchorForTask(task)
    if (anchor && !index[anchor]) index[anchor] = task
  }
  return index
}

export const VA_CLAIM_GUIDE_PATH = '/va-claim/guide'

/**
 * Intent to File was RECEIVED by VA on 2026-05-12 (confirmed against the
 * VA.gov confirmation email on 2026-08-03). It expires 2027-05-12. The board
 * task was not ticked until 2026-06-20 — do not use the tick date as the ITF
 * date; doing so overstates the remaining runway by 39 days.
 */
export const ITF_FILED_DATE = '2026-05-12'
export const ITF_DEADLINE_DATE = '2027-05-12'
