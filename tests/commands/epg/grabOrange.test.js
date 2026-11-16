import fs from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
const { downloadOrange } = require('../../../scripts/commands/epg/grab-orange.cjs')

const channelsXml = `<?xml version="1.0"?><channels>
  <channel site="orangetv.orange.es" lang="es" xmltv_id="Orange.11232" site_id="11232">DAZN Baloncesto 2</channel>
  <channel site="orangetv.orange.es" lang="es" xmltv_id="Orange.999" site_id="999">Canal de prueba</channel>
</channels>`

function block(channelExternalId, name) {
  return [{
    channelExternalId,
    programs: [{
      startDate: Date.parse('2026-11-16T10:00:00Z'),
      endDate: Date.parse('2026-11-16T11:00:00Z'),
      name,
      description: 'Evento',
      attachments: [],
      genres: ['Deportes'].map(value => ({ name: value })),
      seriesName: '',
      seriesSeason: '',
      episodeId: ''
    }]
  }]
}

async function fixture(run) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'orange-download-test-'))
  const channelsPath = path.join(dir, 'channels.xml')
  const outputPath = path.join(dir, 'orange.xml')
  await fs.writeFile(channelsPath, channelsXml)
  try { return await run({ channelsPath, outputPath, dir }) }
  finally { await fs.rm(dir, { recursive: true, force: true }) }
}

test('downloads each of six day/segment URLs once and emits selected channel IDs as valid XMLTV', async () => {
  
  await fixture(async ({ channelsPath, outputPath }) => {
    const calls = []
    const get = async (url, options) => {
      calls.push([url, options])
      const segment = Number(url.match(/_8h_(\d)\.json$/)[1])
      return { status: 200, headers: { 'content-type': 'application/json' }, data: JSON.stringify([
        ...block('11232', `Event ${segment}`), ...block('999', `Other ${segment}`)
      ]) }
    }
    const result = await downloadOrange({ channelsPath, outputPath, days: 2, now: new Date('2026-11-16T00:00:00Z'), get })
    expect(calls).toHaveLength(6)
    expect(new Set(calls.map(x => x[0])).size).toBe(6)
    expect(calls.every(([, options]) => options.headers.Accept === 'application/json')).toBe(true)
    expect(result).toMatchObject({ channels: 2, programmes: 6, errors: [] })
    const xml = await fs.readFile(outputPath, 'utf8')
    expect(xml).toContain('<channel id="Orange.11232">')
    expect(xml).toContain('channel="Orange.11232"')
    expect(xml).toContain('DAZN Baloncesto 2')
    expect(xml).toContain('channel="Orange.999"')
    expect(xml).toMatch(/^<\?xml version="1\.0" encoding="UTF-8"\?>\n<tv>[\s\S]*<\/tv>\n$/)
    expect((xml.match(/<channel\b/g) || []).length).toBe(2)
    expect((xml.match(/<programme\b/g) || []).length).toBe(6)
  })
})

test('deduplicates repeated programs across segments and preserves successful segments after failure', async () => {
  
  await fixture(async ({ channelsPath, outputPath }) => {
    let call = 0
    const get = async () => {
      call++
      if (call === 2) throw new Error('simulated truncated segment')
      return { status: 200, headers: {}, data: JSON.stringify(block('11232', 'Same event')) }
    }
    const result = await downloadOrange({ channelsPath, outputPath, days: 2, now: new Date('2026-11-16T00:00:00Z'), get })
    expect(call).toBe(6)
    expect(result.errors).toHaveLength(1)
    expect(result.programmes).toBe(1)
    const xml = await fs.readFile(outputPath, 'utf8')
    expect((xml.match(/<programme /g) || []).length).toBe(1)
    expect(xml).toContain('Same event')
  })
})
