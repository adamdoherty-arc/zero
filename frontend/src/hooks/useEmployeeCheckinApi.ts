import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''
const BASE = '/api/employee'

export interface SubsystemGrade {
    subsystem: string
    grade: number
    metrics: Record<string, unknown>
    issues: string[]
    wins: string[]
}

export interface EmployeeCheckin {
    id: string
    created_at: string | null
    ops_grade: number | null
    overall_grade: number | null
    subsystem_grades: Record<string, number>
    accomplishments: Record<string, number>
    issues: string[]
    wins: string[]
    legion_task_ids: string[]
    full_report: {
        subsystems?: SubsystemGrade[]
        carousel_report?: Record<string, unknown>
        window_hours?: number
    }
}

async function fetchJson<T>(
    path: string,
    init?: RequestInit & { timeoutMs?: number },
): Promise<T> {
    const { timeoutMs, ...rest } = init ?? {}
    const controller = timeoutMs ? new AbortController() : undefined
    const timer = controller
        ? window.setTimeout(() => controller.abort(), timeoutMs)
        : undefined
    try {
        const res = await fetch(`${API_URL}${path}`, {
            headers: getAuthHeaders(),
            signal: controller?.signal,
            ...rest,
        })
        if (!res.ok) {
            const body = await res.text().catch(() => '')
            throw new Error(`${path} failed: ${res.status}${body ? ` — ${body.slice(0, 180)}` : ''}`)
        }
        return (await res.json()) as T
    } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError') {
            throw new Error(`${path} timed out after ${timeoutMs}ms`)
        }
        throw err
    } finally {
        if (timer) window.clearTimeout(timer)
    }
}

export function useLatestCheckin() {
    return useQuery<EmployeeCheckin>({
        queryKey: ['employee', 'checkin', 'latest'],
        queryFn: () => fetchJson<EmployeeCheckin>(`${BASE}/checkin/latest`),
        refetchInterval: 60_000,
        retry: false,
    })
}

export function useCheckinHistory(days = 14) {
    return useQuery<EmployeeCheckin[]>({
        queryKey: ['employee', 'checkin', 'history', days],
        queryFn: () => fetchJson<EmployeeCheckin[]>(`${BASE}/checkin/history?days=${days}`),
        refetchInterval: 120_000,
    })
}

export function useRunCheckin() {
    const qc = useQueryClient()
    return useMutation<EmployeeCheckin, Error, number | void>({
        mutationFn: async (windowHours) => {
            // Hold the spinner on screen for at least 500ms so the user always
            // sees something happened, even when the backend returns in ~100ms.
            const minDelay = new Promise((resolve) => window.setTimeout(resolve, 500))
            const [result] = await Promise.all([
                fetchJson<EmployeeCheckin>(
                    `${BASE}/checkin/run?window_hours=${windowHours ?? 24}`,
                    { method: 'POST', timeoutMs: 20_000 },
                ),
                minDelay,
            ])
            return result
        },
        onSuccess: (data) => {
            // Seed the cache synchronously so the dashboard flips to the new
            // snapshot immediately, without waiting for a refetch round-trip.
            qc.setQueryData(['employee', 'checkin', 'latest'], data)
            qc.invalidateQueries({ queryKey: ['employee', 'checkin'] })
        },
    })
}
