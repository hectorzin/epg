import { Channel } from 'epg-grabber'

interface MovistarChannelData {
  site: string
  lang: string
  site_id: string
  xmltv_id: string
  name: string
  index: number
}

const ChannelConstructor = Channel as unknown as new (data: MovistarChannelData) => Channel

interface DiscoveredChannel {
  site_id?: string
  name?: string
}

export function mergeMovistarChannels(
  existing: Channel[],
  discovered: DiscoveredChannel[]
): Channel[] {
  const merged = [...existing]
  const known = new Set(
    existing.map(channel =>
      `${channel.site}:${channel.lang || 'es'}:${String(channel.site_id || '').trim().toLowerCase()}`
    )
  )

  for (const item of discovered) {
    const siteId = String(item.site_id || '').trim().toLowerCase()
    const name = String(item.name || '').replace(/\s+/g, ' ').trim()
    const key = `movistarplus.es:es:${siteId}`
    if (!/^[a-z0-9_-]+$/.test(siteId) || !name || known.has(key)) continue

    const channel = new ChannelConstructor({
      site: 'movistarplus.es',
      lang: 'es',
      site_id: siteId,
      xmltv_id: `MovistarPlus.${siteId}`,
      name,
      index: merged.length,
    })
    Object.assign(channel, { _movistarDiscovered: true })
    merged.push(channel)
    known.add(key)
  }

  return merged
}

export async function discoverMovistarChannels(
  existing: Channel[],
  enabled: boolean,
  discover: () => Promise<DiscoveredChannel[]>,
  onError?: (error: Error) => void
): Promise<Channel[]> {
  if (!enabled || !existing.some(channel => channel.site === 'movistarplus.es')) return existing

  try {
    return mergeMovistarChannels(existing, await discover())
  } catch (error) {
    onError?.(error as Error)
    return existing
  }
}
