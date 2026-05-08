import { useMemo, useState } from 'react'
import {
  Utensils,
  Tag,
  Truck,
  CreditCard,
  RefreshCw,
  Sparkles,
  Mail,
  Percent,
  TrendingDown,
} from 'lucide-react'
import {
  useMealStats,
  useMealServices,
  useMealPromos,
  useCardOffers,
  usePortalOffers,
  useShipments,
  useCheapestMeals,
  useHuntPromos,
  useRefreshCatalog,
  useScanShipments,
  useUpdateService,
  type MealService,
  type PriceStackResult,
  type PromoCode,
  type MealShipment,
  type RebatePortalOffer,
} from '@/hooks/useMealsApi'

// ---------------- helpers ----------------

function fmtUsd(n?: number | null): string {
  if (n === null || n === undefined) return '--'
  return `$${n.toFixed(2)}`
}

function timeAgo(iso?: string | null): string {
  if (!iso) return 'never'
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60_000) return 'just now'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
  return `${Math.floor(diff / 86_400_000)}d ago`
}

const STATUS_COLOR: Record<string, string> = {
  delivered: 'bg-green-500/20 text-green-400',
  shipped: 'bg-blue-500/20 text-blue-400',
  out_for_delivery: 'bg-indigo-500/20 text-indigo-400',
  processing: 'bg-yellow-500/20 text-yellow-400',
  pending: 'bg-gray-500/20 text-gray-400',
  delayed: 'bg-orange-500/20 text-orange-400',
  cancelled: 'bg-red-500/20 text-red-400',
  lost: 'bg-red-500/20 text-red-400',
}

function Tab({ active, onClick, children, badge }: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  badge?: number
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors flex items-center gap-2 ${
        active ? 'bg-indigo-600 text-white' : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
      }`}
    >
      {children}
      {badge !== undefined && badge > 0 && (
        <span className={`rounded-full px-2 py-0.5 text-xs ${active ? 'bg-indigo-700' : 'bg-gray-700'}`}>
          {badge}
        </span>
      )}
    </button>
  )
}

function StatCard({ icon: Icon, label, value, color, subtitle }: {
  icon: React.ElementType
  label: string
  value: string | number
  color: string
  subtitle?: string
}) {
  return (
    <div className="bg-gray-800 rounded-lg p-4 border border-gray-700">
      <div className="flex items-center gap-3">
        <div className={`p-2 rounded-lg ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <div className="text-xs text-gray-400 truncate">{label}</div>
          <div className="text-xl font-bold text-gray-100 truncate">{value}</div>
          {subtitle && <div className="text-xs text-gray-500 truncate">{subtitle}</div>}
        </div>
      </div>
    </div>
  )
}

// ---------------- Services tab ----------------

function formatDiscount(p: PromoCode): string {
  if (p.discount_type === 'percent') return `${p.discount_value}% off`
  if (p.discount_type === 'dollar') return `$${p.discount_value} off`
  if (p.discount_type === 'free_shipping') return 'Free ship'
  if (p.discount_type === 'bogo') return 'BOGO'
  return p.discount_type
}

function ServiceCard({
  service,
  quote,
  promos,
  referrals,
  portals,
  shipments,
}: {
  service: MealService
  quote?: PriceStackResult
  promos: PromoCode[]
  referrals: PromoCode[]
  portals: RebatePortalOffer[]
  shipments: MealShipment[]
}) {
  // Find this service's coupon aggregator URL (RetailMeNot) for a quick link
  const slugBase = service.slug.replace(/-/g, '')
  const couponPageUrl = `https://www.retailmenot.com/view/${slugBase}.com`
  const rakutenUrl = `https://www.rakuten.com/${service.slug}.com`
  const updateService = useUpdateService()

  const autoCalendar = service.auto_calendar !== false

  const upcomingShipments = shipments.filter(
    s => s.status !== 'delivered' && s.status !== 'cancelled' && s.status !== 'lost'
  )

  const toggleCalendar = () => {
    updateService.mutate({
      id: service.id,
      updates: { auto_calendar: !autoCalendar },
    })
  }

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-4 hover:border-indigo-500/50 transition-colors flex flex-col">
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-gray-100">{service.name}</h3>
          <div className="text-xs text-gray-400 capitalize">
            {service.tier.replace('_', ' ')} · {service.status}
          </div>
        </div>
        <button
          onClick={toggleCalendar}
          title={autoCalendar ? 'Auto-add deliveries to calendar (click to turn off)' : 'Deliveries not added to calendar (click to turn on)'}
          className={`text-[10px] rounded px-2 py-0.5 shrink-0 ${
            autoCalendar
              ? 'bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30'
              : 'bg-gray-700 text-gray-400 hover:bg-gray-600'
          }`}
        >
          📅 {autoCalendar ? 'ON' : 'OFF'}
        </button>
      </div>

      {service.description && (
        <p className="text-xs text-gray-400 line-clamp-2 mb-2">{service.description}</p>
      )}

      {/* Quick links */}
      <div className="flex flex-wrap gap-2 mb-2">
        <a href={service.website_url} target="_blank" rel="noopener noreferrer"
          className="text-[11px] bg-indigo-500/20 text-indigo-300 rounded px-2 py-0.5 hover:bg-indigo-500/30">
          Site ↗
        </a>
        {service.menu_url && (
          <a href={service.menu_url} target="_blank" rel="noopener noreferrer"
            className="text-[11px] bg-indigo-500/20 text-indigo-300 rounded px-2 py-0.5 hover:bg-indigo-500/30">
            Menu ↗
          </a>
        )}
        <a href={couponPageUrl} target="_blank" rel="noopener noreferrer"
          className="text-[11px] bg-yellow-500/20 text-yellow-300 rounded px-2 py-0.5 hover:bg-yellow-500/30">
          Coupons ↗
        </a>
        <a href={rakutenUrl} target="_blank" rel="noopener noreferrer"
          className="text-[11px] bg-pink-500/20 text-pink-300 rounded px-2 py-0.5 hover:bg-pink-500/30">
          Rakuten ↗
        </a>
      </div>

      {/* Pricing */}
      <div className="flex items-end justify-between py-2 border-t border-gray-700">
        <div>
          <div className="text-xs text-gray-500">Base / meal</div>
          <div className="text-sm text-gray-200">{fmtUsd(service.base_price_per_meal)}</div>
        </div>
        {quote && (
          <div className="text-right">
            <div className="text-xs text-emerald-400">After stack</div>
            <div className="text-sm font-bold text-emerald-300">
              {fmtUsd(quote.price_per_meal)}/meal
            </div>
          </div>
        )}
      </div>

      {/* Top promos for this service (excluding referrals) */}
      {promos.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Top promos</div>
          <div className="space-y-0.5">
            {promos.slice(0, 3).map(p => (
              <div key={p.id} className="flex items-center justify-between text-xs">
                <code className="bg-gray-900 px-1.5 py-0.5 rounded text-indigo-300 text-[11px] truncate max-w-[55%]">
                  {p.code || '(auto)'}
                </code>
                <span className="text-emerald-400 text-[11px]">{formatDiscount(p)}</span>
                <span className="text-gray-500 text-[10px] capitalize">{p.source}</span>
              </div>
            ))}
          </div>
          {/* Description row for the top promo */}
          {promos[0]?.description && (
            <div className="text-[10px] text-gray-400 mt-1 italic line-clamp-2">
              {promos[0].description}
            </div>
          )}
        </div>
      )}

      {/* Referral codes (new-customer only) */}
      {referrals.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1 flex items-center gap-1">
            Referral codes
            <span className="text-orange-400 normal-case text-[9px] bg-orange-500/10 rounded px-1.5 py-0.5">
              new customers only
            </span>
          </div>
          <div className="space-y-0.5">
            {referrals.slice(0, 3).map(p => (
              <div key={p.id} className="flex items-center justify-between text-xs">
                <code className="bg-gray-900 px-1.5 py-0.5 rounded text-orange-300 text-[11px] truncate max-w-[55%]">
                  {p.code || '(link)'}
                </code>
                <span className="text-orange-300 text-[11px]">{formatDiscount(p)}</span>
                <span className="text-gray-500 text-[10px] capitalize">{p.source}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Upcoming deliveries for this service */}
      {upcomingShipments.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Upcoming deliveries</div>
          <div className="space-y-0.5">
            {upcomingShipments.slice(0, 2).map(s => (
              <div key={s.id} className="flex items-center justify-between text-xs">
                <span className={`text-[11px] px-1.5 py-0.5 rounded ${STATUS_COLOR[s.status] ?? 'bg-gray-500/20 text-gray-400'}`}>
                  {s.status.replace(/_/g, ' ')}
                </span>
                <span className="text-gray-300 text-[11px] truncate">
                  {s.expected_delivery
                    ? new Date(s.expected_delivery).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
                    : 'ETA pending'}
                </span>
                {s.tracking_url ? (
                  <a href={s.tracking_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 text-[10px] hover:underline">
                    track
                  </a>
                ) : <span className="text-gray-500 text-[10px]">—</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Portal cashback for this service */}
      {portals.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-700">
          <div className="text-[10px] uppercase tracking-wide text-gray-500 mb-1">Cashback</div>
          <div className="flex flex-wrap gap-1">
            {portals.slice(0, 4).map(p => (
              <span key={p.id} className="text-[10px] bg-pink-500/10 text-pink-300 rounded px-1.5 py-0.5">
                {p.portal}: {p.cashback_percent.toFixed(1)}%
              </span>
            ))}
          </div>
        </div>
      )}

      {service.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2 pt-2 border-t border-gray-700">
          {service.tags.slice(0, 4).map(t => (
            <span key={t} className="text-[10px] bg-gray-700 text-gray-300 rounded px-1.5 py-0.5">
              {t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------- Cheapest tab ----------------

function CheapestTable({ quotes }: { quotes: PriceStackResult[] }) {
  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-gray-900 text-gray-400 text-xs">
          <tr>
            <th className="text-left p-3">#</th>
            <th className="text-left p-3">Service</th>
            <th className="text-right p-3">Base subtotal</th>
            <th className="text-right p-3">Discounts</th>
            <th className="text-right p-3">Cashback</th>
            <th className="text-right p-3">Out of pocket</th>
            <th className="text-right p-3">$ / meal (net)</th>
          </tr>
        </thead>
        <tbody>
          {quotes.map((q, i) => (
            <tr key={q.service_id} className="border-t border-gray-700 hover:bg-gray-700/40">
              <td className="p-3 text-gray-500">{i + 1}</td>
              <td className="p-3 text-gray-100 font-medium">{q.service_name}</td>
              <td className="p-3 text-right text-gray-300">{fmtUsd(q.base_subtotal)}</td>
              <td className="p-3 text-right text-rose-300">-{fmtUsd(q.total_discounts)}</td>
              <td className="p-3 text-right text-emerald-300">-{fmtUsd(q.total_cashback)}</td>
              <td className="p-3 text-right text-gray-200">{fmtUsd(q.final_out_of_pocket)}</td>
              <td className="p-3 text-right font-bold text-emerald-400">{fmtUsd(q.price_per_meal)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------- Promos tab ----------------

function PromoRow({ promo, serviceName }: { promo: PromoCode; serviceName?: string }) {
  return (
    <tr className="border-t border-gray-700 hover:bg-gray-700/40">
      <td className="p-3">
        <code className="bg-gray-900 px-2 py-1 rounded text-xs text-indigo-300">
          {promo.code || '(auto)'}
        </code>
      </td>
      <td className="p-3 text-gray-300">{serviceName || '—'}</td>
      <td className="p-3 text-gray-300">
        {promo.discount_type === 'percent' && `${promo.discount_value}% off`}
        {promo.discount_type === 'dollar' && `$${promo.discount_value} off`}
        {promo.discount_type === 'free_shipping' && 'Free shipping'}
        {promo.discount_type === 'bogo' && 'BOGO'}
        {promo.discount_type === 'bundle' && 'Bundle'}
      </td>
      <td className="p-3 text-gray-400 text-xs capitalize">{promo.source}</td>
      <td className="p-3 text-gray-400 text-xs">
        {promo.new_customer_only && <span className="text-orange-400">New-cust</span>}
        {promo.stackable && <span className="text-emerald-400 ml-1">Stack</span>}
      </td>
      <td className="p-3 text-gray-500 text-xs">
        {promo.expires_at ? timeAgo(promo.expires_at) : '—'}
      </td>
    </tr>
  )
}

// ---------------- Shipments tab ----------------

function ShipmentRow({ ship }: { ship: MealShipment }) {
  const color = STATUS_COLOR[ship.status] ?? 'bg-gray-500/20 text-gray-400'
  return (
    <tr className="border-t border-gray-700 hover:bg-gray-700/40">
      <td className="p-3 text-gray-100 font-medium">{ship.service_name || ship.service_id}</td>
      <td className="p-3 text-gray-300 text-xs">{ship.order_number || '—'}</td>
      <td className="p-3">
        <span className={`px-2 py-0.5 rounded text-xs capitalize ${color}`}>
          {ship.status.replace(/_/g, ' ')}
        </span>
      </td>
      <td className="p-3 text-gray-300 text-xs">{ship.carrier || '—'}</td>
      <td className="p-3 text-xs">
        {ship.tracking_url ? (
          <a href={ship.tracking_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:underline">
            {ship.tracking_number || 'track'}
          </a>
        ) : (
          <span className="text-gray-400">{ship.tracking_number || '—'}</span>
        )}
      </td>
      <td className="p-3 text-gray-300 text-xs">{ship.meal_count ?? '—'}</td>
      <td className="p-3 text-gray-300 text-xs">{fmtUsd(ship.total_charged)}</td>
      <td className="p-3 text-gray-500 text-xs">{timeAgo(ship.updated_at)}</td>
    </tr>
  )
}

// ---------------- Main page ----------------

type TabId = 'overview' | 'services' | 'cheapest' | 'promos' | 'cards' | 'portals' | 'shipments'

export function MealsPage() {
  const [tab, setTab] = useState<TabId>('overview')
  const [mealCount, setMealCount] = useState(6)
  const [newCustomer, setNewCustomer] = useState(false)

  const stats = useMealStats()
  const services = useMealServices()
  const promos = useMealPromos()
  const cards = useCardOffers()
  const portals = usePortalOffers()
  const shipments = useShipments()
  const cheapest = useCheapestMeals(mealCount, newCustomer)

  const huntPromos = useHuntPromos()
  const refreshCatalog = useRefreshCatalog()
  const scanShipments = useScanShipments()

  const servicesById = useMemo(() => {
    const m: Record<string, MealService> = {}
    for (const s of services.data ?? []) m[s.id] = s
    return m
  }, [services.data])

  const quoteByService = useMemo(() => {
    const m: Record<string, PriceStackResult> = {}
    for (const q of cheapest.data ?? []) m[q.service_id] = q
    return m
  }, [cheapest.data])

  const promosByService = useMemo(() => {
    const m: Record<string, PromoCode[]> = {}
    for (const p of promos.data ?? []) {
      if (!p.service_id) continue
      if (p.is_referral) continue
      ;(m[p.service_id] ??= []).push(p)
    }
    for (const sid of Object.keys(m)) {
      m[sid].sort((a, b) => b.discount_value - a.discount_value)
    }
    return m
  }, [promos.data])

  const referralsByService = useMemo(() => {
    const m: Record<string, PromoCode[]> = {}
    for (const p of promos.data ?? []) {
      if (!p.service_id) continue
      if (!p.is_referral) continue
      ;(m[p.service_id] ??= []).push(p)
    }
    for (const sid of Object.keys(m)) {
      m[sid].sort((a, b) => b.discount_value - a.discount_value)
    }
    return m
  }, [promos.data])

  const portalsByService = useMemo(() => {
    const m: Record<string, RebatePortalOffer[]> = {}
    for (const p of portals.data ?? []) {
      if (!p.service_id) continue
      ;(m[p.service_id] ??= []).push(p)
    }
    for (const sid of Object.keys(m)) {
      m[sid].sort((a, b) => b.cashback_percent - a.cashback_percent)
    }
    return m
  }, [portals.data])

  const shipmentsByService = useMemo(() => {
    const m: Record<string, MealShipment[]> = {}
    for (const s of shipments.data ?? []) {
      ;(m[s.service_id] ??= []).push(s)
    }
    // Sort upcoming-soonest first per service
    for (const sid of Object.keys(m)) {
      m[sid].sort((a, b) => {
        const ad = a.expected_delivery ? new Date(a.expected_delivery).getTime() : Infinity
        const bd = b.expected_delivery ? new Date(b.expected_delivery).getTime() : Infinity
        return ad - bd
      })
    }
    return m
  }, [shipments.data])

  return (
    <div className="p-6 space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-100 flex items-center gap-2">
            <Utensils className="w-6 h-6 text-indigo-400" />
            Meal Manager
          </h1>
          <p className="text-sm text-gray-400 mt-1">
            Catalog, promo stacking, shipment tracking, best-price discovery.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => scanShipments.mutate()}
            disabled={scanShipments.isPending}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-200 flex items-center gap-2 disabled:opacity-50"
          >
            <Mail className="w-4 h-4" />
            Scan email
          </button>
          <button
            onClick={() => huntPromos.mutate(undefined)}
            disabled={huntPromos.isPending}
            className="px-3 py-2 bg-gray-700 hover:bg-gray-600 rounded-lg text-sm text-gray-200 flex items-center gap-2 disabled:opacity-50"
          >
            <Sparkles className="w-4 h-4" />
            Hunt promos
          </button>
          <button
            onClick={() => refreshCatalog.mutate(undefined)}
            disabled={refreshCatalog.isPending}
            className="px-3 py-2 bg-indigo-600 hover:bg-indigo-700 rounded-lg text-sm text-white flex items-center gap-2 disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${refreshCatalog.isPending ? 'animate-spin' : ''}`} />
            Refresh catalog
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats.data && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <StatCard
            icon={Utensils}
            label="Services"
            value={`${stats.data.tracked_services}/${stats.data.total_services}`}
            color="bg-indigo-500/20 text-indigo-400"
            subtitle="tracked"
          />
          <StatCard
            icon={TrendingDown}
            label="Cheapest / meal"
            value={fmtUsd(stats.data.cheapest_per_meal_usd)}
            color="bg-emerald-500/20 text-emerald-400"
            subtitle={stats.data.cheapest_service_name ?? '—'}
          />
          <StatCard
            icon={Tag}
            label="Active promos"
            value={stats.data.active_promos}
            color="bg-yellow-500/20 text-yellow-400"
            subtitle={timeAgo(stats.data.last_promo_hunt_at)}
          />
          <StatCard
            icon={CreditCard}
            label="Card offers"
            value={stats.data.active_card_offers}
            color="bg-purple-500/20 text-purple-400"
          />
          <StatCard
            icon={Percent}
            label="Portal offers"
            value={stats.data.active_portal_offers}
            color="bg-pink-500/20 text-pink-400"
          />
          <StatCard
            icon={Truck}
            label="In transit"
            value={stats.data.in_transit_shipments}
            color="bg-blue-500/20 text-blue-400"
            subtitle={timeAgo(stats.data.last_shipment_scan_at)}
          />
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 flex-wrap">
        <Tab active={tab === 'overview'} onClick={() => setTab('overview')}>Overview</Tab>
        <Tab active={tab === 'services'} onClick={() => setTab('services')} badge={services.data?.length}>Services</Tab>
        <Tab active={tab === 'cheapest'} onClick={() => setTab('cheapest')}>Cheapest</Tab>
        <Tab active={tab === 'promos'} onClick={() => setTab('promos')} badge={promos.data?.length}>Promos</Tab>
        <Tab active={tab === 'cards'} onClick={() => setTab('cards')} badge={cards.data?.length}>Card offers</Tab>
        <Tab active={tab === 'portals'} onClick={() => setTab('portals')} badge={portals.data?.length}>Portals</Tab>
        <Tab active={tab === 'shipments'} onClick={() => setTab('shipments')} badge={shipments.data?.length}>Shipments</Tab>
      </div>

      {/* Panels */}
      {tab === 'overview' && (
        <div className="space-y-4">
          {/* Upcoming deliveries — sorted by ETA */}
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
              <Truck className="w-4 h-4" /> Upcoming deliveries
            </h2>
            {(shipments.data ?? [])
              .filter(s => s.status !== 'delivered' && s.status !== 'cancelled' && s.status !== 'lost')
              .sort((a, b) => {
                const ad = a.expected_delivery ? new Date(a.expected_delivery).getTime() : Infinity
                const bd = b.expected_delivery ? new Date(b.expected_delivery).getTime() : Infinity
                return ad - bd
              })
              .slice(0, 5)
              .map(s => (
                <div key={s.id} className="flex items-center justify-between py-2 border-t border-gray-700 first:border-0 gap-3">
                  <div className="text-sm min-w-0 flex-1">
                    <span className="text-gray-100 font-medium truncate">{s.service_name || s.service_id}</span>
                    <span className="text-gray-500 ml-2 text-xs">{s.order_number || ''}</span>
                  </div>
                  <span className="text-xs text-gray-300">
                    {s.expected_delivery
                      ? new Date(s.expected_delivery).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
                      : 'ETA pending'}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded ${STATUS_COLOR[s.status] ?? 'bg-gray-500/20 text-gray-400'}`}>
                    {s.status.replace(/_/g, ' ')}
                  </span>
                  {s.tracking_url && (
                    <a href={s.tracking_url} target="_blank" rel="noopener noreferrer"
                      className="text-xs text-indigo-400 hover:underline shrink-0">
                      track ↗
                    </a>
                  )}
                </div>
              ))}
            {(shipments.data ?? []).filter(s => s.status !== 'delivered' && s.status !== 'cancelled' && s.status !== 'lost').length === 0 && (
              <div className="text-sm text-gray-500 py-2">No upcoming deliveries. Click “Scan email”.</div>
            )}
          </div>
          <div className="bg-gray-800 border border-gray-700 rounded-lg p-4">
            <h2 className="text-sm font-semibold text-gray-200 mb-3 flex items-center gap-2">
              <Sparkles className="w-4 h-4" /> Hottest promos
            </h2>
            {[...(promos.data ?? [])]
              .sort((a, b) => b.discount_value - a.discount_value)
              .slice(0, 10)
              .map(p => (
                <div key={p.id} className="grid grid-cols-[minmax(0,1fr)_auto_auto_auto] items-center gap-3 py-1.5 border-t border-gray-700 first:border-0">
                  <span className="text-sm text-gray-200 truncate">
                    {p.service_id ? (servicesById[p.service_id]?.name ?? '—') : 'Any merchant'}
                  </span>
                  <code className="bg-gray-900 px-2 py-0.5 rounded text-xs text-indigo-300 truncate max-w-[140px]">
                    {p.code || '(auto)'}
                  </code>
                  <span className="text-xs text-emerald-400 whitespace-nowrap">
                    {formatDiscount(p)}
                  </span>
                  <span className="text-xs text-gray-500 capitalize whitespace-nowrap">{p.source}</span>
                </div>
              ))}
            {(promos.data ?? []).length === 0 && (
              <div className="text-sm text-gray-500 py-2">No promos yet. Click “Hunt promos”.</div>
            )}
          </div>
        </div>
      )}

      {tab === 'services' && (
        <div className="space-y-4">
          {services.isLoading && <div className="text-gray-400 text-sm">Loading services…</div>}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {(services.data ?? []).map(s => (
              <ServiceCard
                key={s.id}
                service={s}
                quote={quoteByService[s.id]}
                promos={promosByService[s.id] ?? []}
                referrals={referralsByService[s.id] ?? []}
                portals={portalsByService[s.id] ?? []}
                shipments={shipmentsByService[s.id] ?? []}
              />
            ))}
          </div>
        </div>
      )}

      {tab === 'cheapest' && (
        <div className="space-y-4">
          <div className="flex items-center gap-3 bg-gray-800 border border-gray-700 rounded-lg p-3">
            <label className="text-sm text-gray-300">Meals per week:</label>
            <input
              type="number"
              min={1}
              max={24}
              value={mealCount}
              onChange={e => setMealCount(Math.max(1, Math.min(24, +e.target.value || 6)))}
              className="bg-gray-900 border border-gray-700 rounded px-2 py-1 w-20 text-sm text-gray-100"
            />
            <label className="text-sm text-gray-300 ml-4 flex items-center gap-2">
              <input
                type="checkbox"
                checked={newCustomer}
                onChange={e => setNewCustomer(e.target.checked)}
                className="rounded"
              />
              New customer (include first-order promos)
            </label>
          </div>
          {cheapest.isLoading && <div className="text-gray-400 text-sm">Computing best stacks…</div>}
          {cheapest.data && <CheapestTable quotes={cheapest.data} />}
        </div>
      )}

      {tab === 'promos' && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-gray-400 text-xs">
              <tr>
                <th className="text-left p-3">Code</th>
                <th className="text-left p-3">Service</th>
                <th className="text-left p-3">Discount</th>
                <th className="text-left p-3">Source</th>
                <th className="text-left p-3">Flags</th>
                <th className="text-left p-3">Expires</th>
              </tr>
            </thead>
            <tbody>
              {(promos.data ?? []).map(p => (
                <PromoRow key={p.id} promo={p} serviceName={p.service_id ? servicesById[p.service_id]?.name : undefined} />
              ))}
            </tbody>
          </table>
          {(promos.data ?? []).length === 0 && (
            <div className="p-6 text-center text-gray-500 text-sm">No promos yet — hunt them.</div>
          )}
        </div>
      )}

      {tab === 'cards' && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-gray-400 text-xs">
              <tr>
                <th className="text-left p-3">Network</th>
                <th className="text-left p-3">Merchant</th>
                <th className="text-left p-3">Offer</th>
                <th className="text-left p-3">Min spend</th>
                <th className="text-left p-3">Expires</th>
                <th className="text-left p-3">Source</th>
              </tr>
            </thead>
            <tbody>
              {(cards.data ?? []).map(c => (
                <tr key={c.id} className="border-t border-gray-700 hover:bg-gray-700/40">
                  <td className="p-3 capitalize text-gray-200">{c.network}</td>
                  <td className="p-3 text-gray-100">{c.merchant_name}</td>
                  <td className="p-3 text-gray-300">
                    {c.offer_type === 'percent' ? `${c.value}%` : `$${c.value}`}
                  </td>
                  <td className="p-3 text-gray-400">{c.min_spend ? `$${c.min_spend}` : '—'}</td>
                  <td className="p-3 text-gray-500 text-xs">{c.expires_at ? timeAgo(c.expires_at) : '—'}</td>
                  <td className="p-3 text-xs text-gray-400">{c.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(cards.data ?? []).length === 0 && (
            <div className="p-6 text-center text-gray-500 text-sm">
              No card offers tracked yet. Chase/Amex offer emails auto-populate here, or add manually via API.
            </div>
          )}
        </div>
      )}

      {tab === 'portals' && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-gray-400 text-xs">
              <tr>
                <th className="text-left p-3">Portal</th>
                <th className="text-left p-3">Merchant</th>
                <th className="text-left p-3">Cashback %</th>
                <th className="text-left p-3">Flat</th>
                <th className="text-left p-3">Link</th>
              </tr>
            </thead>
            <tbody>
              {(portals.data ?? []).map(p => (
                <tr key={p.id} className="border-t border-gray-700 hover:bg-gray-700/40">
                  <td className="p-3 capitalize text-gray-200">{p.portal.replace('_', ' ')}</td>
                  <td className="p-3 text-gray-100">{p.merchant_name}</td>
                  <td className="p-3 text-emerald-400 font-semibold">{p.cashback_percent.toFixed(1)}%</td>
                  <td className="p-3 text-gray-300">{p.cashback_flat ? `$${p.cashback_flat}` : '—'}</td>
                  <td className="p-3">
                    {p.source_url && (
                      <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="text-indigo-400 text-xs hover:underline">
                        open ↗
                      </a>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(portals.data ?? []).length === 0 && (
            <div className="p-6 text-center text-gray-500 text-sm">No portal offers yet.</div>
          )}
        </div>
      )}

      {tab === 'shipments' && (
        <div className="bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-900 text-gray-400 text-xs">
              <tr>
                <th className="text-left p-3">Service</th>
                <th className="text-left p-3">Order</th>
                <th className="text-left p-3">Status</th>
                <th className="text-left p-3">Carrier</th>
                <th className="text-left p-3">Tracking</th>
                <th className="text-left p-3">Meals</th>
                <th className="text-left p-3">Total</th>
                <th className="text-left p-3">Updated</th>
              </tr>
            </thead>
            <tbody>
              {(shipments.data ?? []).map(s => (
                <ShipmentRow key={s.id} ship={s} />
              ))}
            </tbody>
          </table>
          {(shipments.data ?? []).length === 0 && (
            <div className="p-6 text-center text-gray-500 text-sm">No shipments detected yet. Click “Scan email”.</div>
          )}
        </div>
      )}
    </div>
  )
}

export default MealsPage
