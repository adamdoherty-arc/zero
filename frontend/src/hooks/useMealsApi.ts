import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getAuthHeaders } from '@/lib/auth'

const API_URL = ''

// ---------- Types ----------

export type MealServiceStatus = 'discovered' | 'tracked' | 'used' | 'paused' | 'rejected'
export type MealServiceTier = 'prepared' | 'meal_kit' | 'frozen' | 'subscription_box' | 'grocery' | 'unknown'

export interface MealService {
  id: string
  name: string
  slug: string
  website_url: string
  menu_url?: string | null
  email_sender_patterns: string[]
  tier: MealServiceTier
  status: MealServiceStatus
  description?: string | null
  base_price_per_meal?: number | null
  shipping_fee?: number | null
  min_order_meals?: number | null
  tags: string[]
  notes?: string | null
  auto_calendar?: boolean
  last_catalog_refresh_at?: string | null
  created_at: string
  updated_at: string
}

export interface MealMenuItem {
  id: string
  service_id: string
  name: string
  description?: string | null
  base_price?: number | null
  calories?: number | null
  protein_g?: number | null
  tags: string[]
  image_url?: string | null
  source_url?: string | null
  available: boolean
  first_seen_at: string
  last_seen_at: string
}

export type PromoSource =
  | 'direct' | 'rakuten' | 'rakuten_advertising' | 'honey' | 'retailmenot'
  | 'coupert' | 'kudos' | 'knoji' | 'capital_one_shopping'
  | 'slickdeals' | 'reddit' | 'referral' | 'signup_intercept' | 'vision'
  | 'email' | 'manual' | 'couponfollow' | 'wethrift' | 'other'
export type PromoDiscountType = 'percent' | 'dollar' | 'free_shipping' | 'bogo' | 'bundle'

export interface PromoCode {
  id: string
  code?: string | null
  service_id?: string | null
  source: PromoSource
  source_url?: string | null
  discount_type: PromoDiscountType
  discount_value: number
  description?: string | null
  min_order?: number | null
  new_customer_only: boolean
  stackable: boolean
  verified: boolean
  times_seen: number
  is_referral?: boolean
  expires_at?: string | null
  first_seen_at: string
  last_seen_at: string
}

export type CardNetwork = 'chase' | 'amex' | 'citi' | 'capital_one' | 'discover' | 'other'

export interface CardOffer {
  id: string
  network: CardNetwork
  card_nickname?: string | null
  merchant_name: string
  service_id?: string | null
  offer_type: PromoDiscountType
  value: number
  min_spend?: number | null
  expires_at?: string | null
  activated: boolean
  used: boolean
  source: string
  notes?: string | null
}

export type RebatePortal = 'rakuten' | 'topcashback' | 'befrugal' | 'capital_one_shopping' | 'other'

export interface RebatePortalOffer {
  id: string
  portal: RebatePortal
  service_id?: string | null
  merchant_name: string
  cashback_percent: number
  cashback_flat?: number | null
  new_customer_only: boolean
  source_url?: string | null
  expires_at?: string | null
}

export type ShipmentStatus =
  | 'pending' | 'processing' | 'shipped' | 'out_for_delivery'
  | 'delivered' | 'delayed' | 'lost' | 'cancelled'

export interface MealShipment {
  id: string
  service_id: string
  service_name?: string | null
  order_number?: string | null
  carrier?: string | null
  tracking_number?: string | null
  tracking_url?: string | null
  status: ShipmentStatus
  expected_delivery?: string | null
  delivered_at?: string | null
  meal_count?: number | null
  total_charged?: number | null
  created_at: string
  updated_at: string
  subject?: string | null
}

export interface PriceStackComponent {
  kind: string
  label: string
  amount: number
  reference_id?: string | null
  notes?: string | null
}

export interface PriceStackResult {
  service_id: string
  service_name: string
  meal_count: number
  base_subtotal: number
  shipping: number
  total_discounts: number
  total_cashback: number
  final_out_of_pocket: number
  final_after_cashback: number
  price_per_meal: number
  best_promo_id?: string | null
  best_card_offer_id?: string | null
  best_portal_offer_id?: string | null
  components: PriceStackComponent[]
  notes: string[]
  computed_at: string
}

export interface MealManagerStats {
  total_services: number
  tracked_services: number
  total_menu_items: number
  active_promos: number
  active_card_offers: number
  active_portal_offers: number
  in_transit_shipments: number
  upcoming_deliveries: number
  cheapest_per_meal_usd?: number | null
  cheapest_service_name?: string | null
  last_promo_hunt_at?: string | null
  last_catalog_refresh_at?: string | null
  last_shipment_scan_at?: string | null
}

// ---------- Query keys ----------

const keys = {
  all: ['meals'] as const,
  stats: () => [...keys.all, 'stats'] as const,
  services: () => [...keys.all, 'services'] as const,
  service: (id: string) => [...keys.all, 'service', id] as const,
  menu: (serviceId: string) => [...keys.all, 'menu', serviceId] as const,
  promos: (serviceId?: string) => [...keys.all, 'promos', serviceId ?? 'all'] as const,
  cards: () => [...keys.all, 'cards'] as const,
  portals: () => [...keys.all, 'portals'] as const,
  shipments: () => [...keys.all, 'shipments'] as const,
  cheapest: (mealCount: number, newCustomer: boolean) =>
    [...keys.all, 'cheapest', mealCount, newCustomer] as const,
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...getAuthHeaders(), 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

// ---------- Hooks ----------

export function useMealStats() {
  return useQuery({
    queryKey: keys.stats(),
    queryFn: () => fetchJson<MealManagerStats>('/api/meals/stats'),
    staleTime: 30_000,
  })
}

export function useMealServices(params?: { status?: MealServiceStatus; tier?: MealServiceTier }) {
  return useQuery({
    queryKey: [...keys.services(), params],
    queryFn: () => {
      const q = new URLSearchParams()
      if (params?.status) q.append('status', params.status)
      if (params?.tier) q.append('tier', params.tier)
      return fetchJson<MealService[]>(`/api/meals/services?${q.toString()}`)
    },
    staleTime: 60_000,
  })
}

export function useMealMenu(serviceId: string) {
  return useQuery({
    queryKey: keys.menu(serviceId),
    queryFn: () => fetchJson<MealMenuItem[]>(`/api/meals/services/${serviceId}/menu`),
    enabled: !!serviceId,
  })
}

export function useMealPromos(serviceId?: string, activeOnly = true) {
  return useQuery({
    queryKey: keys.promos(serviceId),
    queryFn: () => {
      const q = new URLSearchParams()
      if (serviceId) q.append('service_id', serviceId)
      q.append('active_only', String(activeOnly))
      return fetchJson<PromoCode[]>(`/api/meals/promos?${q.toString()}`)
    },
    staleTime: 60_000,
  })
}

export function useCardOffers(serviceId?: string) {
  return useQuery({
    queryKey: [...keys.cards(), serviceId],
    queryFn: () => {
      const q = new URLSearchParams()
      if (serviceId) q.append('service_id', serviceId)
      return fetchJson<CardOffer[]>(`/api/meals/card-offers?${q.toString()}`)
    },
  })
}

export function usePortalOffers(serviceId?: string) {
  return useQuery({
    queryKey: [...keys.portals(), serviceId],
    queryFn: () => {
      const q = new URLSearchParams()
      if (serviceId) q.append('service_id', serviceId)
      return fetchJson<RebatePortalOffer[]>(`/api/meals/portal-offers?${q.toString()}`)
    },
  })
}

export function useShipments(serviceId?: string) {
  return useQuery({
    queryKey: [...keys.shipments(), serviceId],
    queryFn: () => {
      const q = new URLSearchParams()
      if (serviceId) q.append('service_id', serviceId)
      return fetchJson<MealShipment[]>(`/api/meals/shipments?${q.toString()}`)
    },
    staleTime: 30_000,
  })
}

export function useCheapestMeals(mealCount = 6, newCustomer = false) {
  return useQuery({
    queryKey: keys.cheapest(mealCount, newCustomer),
    queryFn: () =>
      fetchJson<PriceStackResult[]>(
        `/api/meals/cheapest?meal_count=${mealCount}&new_customer=${newCustomer}`
      ),
    staleTime: 60_000,
  })
}

// ---------- Mutations ----------

export function useHuntPromos() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (serviceId?: string) =>
      fetchJson<{ status: string; discovered?: number; updated?: number }>(
        `/api/meals/promos/hunt${serviceId ? `?service_id=${serviceId}` : ''}`,
        { method: 'POST' }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useRefreshCatalog() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (serviceId?: string) =>
      fetchJson<{ status?: string }>(
        `/api/meals/catalog/refresh${serviceId ? `?service_id=${serviceId}` : ''}`,
        { method: 'POST' }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useScanShipments() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      fetchJson<{ status: string; examined: number; shipments: number; card_offers: number }>(
        `/api/meals/shipments/scan`,
        { method: 'POST' }
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export interface MealServiceUpdate {
  status?: MealServiceStatus
  menu_url?: string | null
  email_sender_patterns?: string[]
  tier?: MealServiceTier
  description?: string | null
  base_price_per_meal?: number | null
  shipping_fee?: number | null
  min_order_meals?: number | null
  tags?: string[]
  notes?: string | null
  auto_calendar?: boolean
}

export function useUpdateService() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ id, updates }: { id: string; updates: MealServiceUpdate }) => {
      const res = await fetch(`${API_URL}/api/meals/services/${id}`, {
        method: 'PATCH',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(updates),
      })
      if (!res.ok) throw new Error('Failed to update service')
      return res.json() as Promise<MealService>
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.services() })
    },
  })
}

export function useCreateCardOffer() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<CardOffer> & { network: CardNetwork; merchant_name: string; value: number; offer_type: PromoDiscountType }) =>
      fetchJson<CardOffer>(`/api/meals/card-offers`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.cards() })
      qc.invalidateQueries({ queryKey: keys.stats() })
    },
  })
}

export function useCreatePromo() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: Partial<PromoCode> & { source: PromoSource; discount_type: PromoDiscountType; discount_value: number }) =>
      fetchJson<PromoCode>(`/api/meals/promos`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.all })
    },
  })
}

export function useComputePriceStack() {
  return useMutation({
    mutationFn: (body: {
      service_id: string
      meal_count?: number
      new_customer?: boolean
      include_shipping?: boolean
      card_network?: CardNetwork
      portal_preference?: RebatePortal
    }) =>
      fetchJson<PriceStackResult>(`/api/meals/price-stack`, {
        method: 'POST',
        body: JSON.stringify(body),
      }),
  })
}
