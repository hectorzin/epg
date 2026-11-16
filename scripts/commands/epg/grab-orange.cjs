#!/usr/bin/env node
const axios = require('axios')
const dayjs = require('dayjs')
const utc = require('dayjs/plugin/utc')
const fs = require('node:fs/promises')
const path = require('node:path')
const orange = require('../../../sites/orangetv.orange.es/orangetv.orange.es.config.js')

dayjs.extend(utc)

async function downloadOrange({ channelsPath, outputPath, days = 2, now = new Date(), get = axios.get }) {
  const channelsXml = await fs.readFile(channelsPath, 'utf8')
  const channels = [...channelsXml.matchAll(/<channel\b([^>]*)>([\s\S]*?)<\/channel>/g)].map(match => {
    const attrs = Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(a => [a[1], a[2]]))
    return { ...attrs, name: match[2].replace(/<[^>]*>/g, '').trim() }
  }).filter(channel => channel.site_id && channel.xmltv_id && channel.name)
  const bySiteId = new Map(channels.map(channel => [channel.site_id, channel]))
  const programmes = new Map(channels.map(channel => [channel.xmltv_id, new Map()]))
  const errors = []
  const baseDate = dayjs.utc(now).startOf('day')
  for (let offset = 0; offset < days; offset++) {
    const date = baseDate.add(offset, 'day')
    for (let segment = 1; segment <= 3; segment++) {
      const url = orange.url({ date, segment })
      try {
        const response = await get(url, { headers: { Accept: 'application/json' }, timeout: 30000, responseType: 'text' })
        const raw = typeof response.data === 'string' ? response.data : JSON.stringify(response.data)
        const blocks = JSON.parse(raw)
        if (!Array.isArray(blocks)) throw new Error(`expected JSON array, got ${typeof blocks}`)
        for (const block of blocks) {
          const channel = bySiteId.get(String(block.channelExternalId))
          if (!channel) continue
          for (const item of Array.isArray(block.programs) ? block.programs : []) {
            const p = orange.convertProgram(item)
            if (!p.start.isValid() || !p.stop.isValid() || !p.title) continue
            programmes.get(channel.xmltv_id).set(`${p.start.valueOf()}|${p.stop.valueOf()}|${p.title}`, p)
          }
        }
        console.log(`Orange ${date.format('YYYY-MM-DD')} segment ${segment}: HTTP ${response.status}, ${raw.length} bytes`)
      } catch (error) {
        const message = `Orange ${date.format('YYYY-MM-DD')} segment ${segment} failed (${url}): ${error.message}`
        errors.push(message)
        console.warn(`WARNING: ${message}`)
      }
    }
  }
  const escape = value => String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;')
  const lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<tv>']
  for (const c of channels) lines.push(`  <channel id="${escape(c.xmltv_id)}"><display-name>${escape(c.name)}</display-name></channel>`)
  let count = 0
  for (const c of channels) for (const p of programmes.get(c.xmltv_id).values()) {
    const stamp = value => value.utc().format('YYYYMMDDHHmmss[ +0000]')
    lines.push(`  <programme start="${stamp(p.start)}" stop="${stamp(p.stop)}" channel="${escape(c.xmltv_id)}">`)
    for (const [tag, values] of [['title', [p.title]], ['sub-title', [p.sub_title]], ['desc', [p.description]], ['category', p.category || []]])
      for (const value of values.filter(Boolean)) lines.push(`    <${tag}>${escape(value)}</${tag}>`)
    if (p.icon) lines.push(`    <icon src="${escape(p.icon)}"/>`)
    lines.push('  </programme>')
    count++
  }
  lines.push('</tv>')
  await fs.mkdir(path.dirname(outputPath), { recursive: true })
  await fs.writeFile(outputPath, `${lines.join('\n')}\n`, 'utf8')
  console.log(`Orange XMLTV written: ${outputPath}; ${channels.length} channels, ${count} programmes; ${errors.length} segment failures`)
  return { channels: channels.length, programmes: count, errors }
}

module.exports = { downloadOrange }
if (require.main === module) {
  const args = Object.fromEntries(process.argv.slice(2).map(arg => { const [key, ...value] = arg.replace(/^--/, '').split('='); return [key, value.join('=')] }))
  downloadOrange({ channelsPath: args.channels, outputPath: args.output, days: Number(args.days || 2) }).catch(error => { console.error(error); process.exitCode = 1 })
}
