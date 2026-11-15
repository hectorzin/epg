import {
  discoverMovistarChannels,
  mergeMovistarChannels
} from '../../../scripts/commands/epg/movistarChannels'
import { parseChannels } from 'epg-grabber'

describe('mergeMovistarChannels', () => {
  const existing = parseChannels(`
    <channels>
      <channel site="movistarplus.es" lang="es" xmltv_id="BasketballChannel.es" site_id="mbalct" logo="https://logo.example/hoops.png">M+ Baloncesto</channel>
      <channel site="orangetv.orange.es" lang="es" xmltv_id="La1.es" site_id="1010">La 1</channel>
    </channels>
  `)

  it('preserves existing metadata and adds new stable IDs without duplicates', () => {
    const merged = mergeMovistarChannels(existing, [
      { site_id: 'MBALCT', name: 'Nombre alternativo' },
      { site_id: 'DAZBA', name: ' DAZN   Baloncesto ' },
      { site_id: 'dazba', name: 'DAZN Baloncesto duplicado' },
      { site_id: '../bad', name: 'Invalid' },
      { site_id: 'vam2sd', name: '' }
    ])

    expect(merged).toHaveLength(3)
    expect(merged[0]).toBe(existing[0])
    expect(merged[0]).toMatchObject({
      xmltv_id: 'BasketballChannel.es',
      lang: 'es',
      icon: 'https://logo.example/hoops.png',
      name: 'M+ Baloncesto'
    })
    expect(merged[1]).toBe(existing[1])
    expect(merged[2]).toMatchObject({
      site: 'movistarplus.es',
      lang: 'es',
      site_id: 'dazba',
      xmltv_id: 'MovistarPlus.dazba',
      name: 'DAZN Baloncesto'
    })
  })

  it('keeps all XML channels when discovery is empty or incomplete', () => {
    expect(mergeMovistarChannels(existing, [])).toEqual(existing)
    expect(mergeMovistarChannels(existing, [{ site_id: 'mbalct', name: 'Only one result' }])).toEqual(
      existing
    )
  })

  it('falls back to the XML channels when discovery fails', async () => {
    const onError = jest.fn()
    const result = await discoverMovistarChannels(
      existing,
      true,
      async () => {
        throw new Error('network unavailable')
      },
      onError
    )

    expect(result).toEqual(existing)
    expect(onError).toHaveBeenCalledWith(expect.objectContaining({ message: 'network unavailable' }))
  })

  it('does not call discovery when the option is disabled', async () => {
    const discover = jest.fn()
    await expect(discoverMovistarChannels(existing, false, discover)).resolves.toBe(existing)
    expect(discover).not.toHaveBeenCalled()
  })
})
