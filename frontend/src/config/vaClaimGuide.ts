/**
 * Maps VA Claim board tasks to their explainer section in VaClaimGuidePage.
 * Single source of truth so the board (task cards + detail dialog) and the
 * guide page ("Learn more" / "Open on board" links) never drift apart.
 */
export interface VaGuideSection {
  /** Anchor slug used as the section id + URL hash (/va-claim/guide#id). */
  id: string
  title: string
  /** Board task ids (ptask-...) this section explains. */
  taskIds: string[]
}

export const VA_GUIDE_SECTIONS: VaGuideSection[] = [
  { id: 'strategy', title: 'Overall strategy (TL;DR)', taskIds: ['ptask-b4d69d8ed04c'] },
  { id: 'intent-to-file', title: 'Intent to File — VA Form 21-0966', taskIds: ['ptask-6d5818a69ce4'] },
  { id: 'digital-accounts', title: 'Digital accounts (VA.gov, MyHealtheVet, milConnect, eVetRecs)', taskIds: ['ptask-fb6be90fa7cc'] },
  { id: 'ompf-strs', title: 'OMPF + Service Treatment Records', taskIds: ['ptask-ea9e75a0210a'] },
  { id: 'va-health-care', title: 'VA health care enrollment', taskIds: ['ptask-f94d26c40b2f'] },
  { id: 'cvso-poa', title: 'CVSO / DAV appointment + Power of Attorney — VA Form 21-22', taskIds: ['ptask-48def01570b4'] },
  { id: 'gi-consult', title: 'GI consult + EGD / barium swallow', taskIds: ['ptask-c2fa773ea065'] },
  { id: 'buddy-statements', title: 'Buddy statements — VA Form 21-10210', taskIds: ['ptask-6fad49e1fca7'] },
  { id: 'personal-statement', title: 'Personal statement — VA Form 21-4138', taskIds: ['ptask-7ce2d37358e7'] },
  { id: 'evidence-packet', title: 'Medical evidence packet', taskIds: ['ptask-52b5b8765666'] },
  { id: 'gi-nexus', title: 'GI nexus letter', taskIds: ['ptask-2811de903469'] },
  { id: 'anxiety-nexus', title: 'Anxiety nexus paragraph', taskIds: ['ptask-3d6fa0d5fa47'] },
  { id: 'ae-rating', title: 'Verify AE rating (tinnitus)', taskIds: ['ptask-55bcda074240'] },
  { id: 'form-526ez', title: 'Submit VA Form 21-526EZ — the main claim', taskIds: ['ptask-13453b116577'] },
  { id: 'cp-exams', title: 'C&P exams (GI / Mental Health / Audio)', taskIds: ['ptask-fa8a3820c833'] },
  { id: 'symptom-log', title: 'Symptom log for the C&P exams', taskIds: ['ptask-3c88e7114e1e'] },
  { id: 'narrative-gerd', title: 'Narrative — GERD / Hiatal Hernia / Post-Nissen', taskIds: ['ptask-230babb414e2'] },
  { id: 'narrative-anxiety', title: 'Narrative — Anxiety secondary to GI chain', taskIds: ['ptask-f11f744679d5'] },
  { id: 'narrative-tinnitus', title: 'Narrative — Tinnitus', taskIds: ['ptask-70aa714a5f5b'] },
  { id: 'rating-tracker', title: 'Rating estimate tracker', taskIds: ['ptask-bde76f6b6856'] },
  { id: 'after-decision', title: 'After-decision plan (appeals)', taskIds: ['ptask-bddf73460d9b'] },
]

const TASK_ID_TO_ANCHOR: Record<string, string> = VA_GUIDE_SECTIONS.reduce(
  (acc, section) => {
    for (const taskId of section.taskIds) acc[taskId] = section.id
    return acc
  },
  {} as Record<string, string>,
)

export function getGuideAnchorForTask(taskId: string): string | undefined {
  return TASK_ID_TO_ANCHOR[taskId]
}

export const VA_CLAIM_GUIDE_PATH = '/va-claim/guide'
