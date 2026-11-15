import { Collection, Logger } from '@freearhey/core'
import { Channel, EPGGrabber, parseChannels } from 'epg-grabber'
import { InternalAxiosRequestConfig } from 'axios'
import { QueueCreator } from '../../../scripts/core/queueCreator'
import { mergeMovistarChannels } from '../../../scripts/commands/epg/movistarChannels'

jest.mock('socks-proxy-agent', () => ({
  SocksProxyAgent: jest.fn()
}))

it('passes a discovered Channel instance through the queue to EPGGrabber.grab', async () => {
  const existing = parseChannels(`
    <channels>
      <channel site="movistarplus.es" lang="es" xmltv_id="Existing.es" site_id="existing">Existing</channel>
    </channels>
  `)
  const merged = mergeMovistarChannels(existing, [
    { site_id: 'newchannel', name: 'New Channel' }
  ])
  const options = {
    output: 'unused.xml',
    discoverChannels: true,
    gzip: false,
    curl: false,
    maxConnections: 1,
    days: 1
  }
  const adapter = jest.fn(async (config: InternalAxiosRequestConfig) => ({
    data: Buffer.from('<html></html>'),
    status: 200,
    statusText: 'OK',
    headers: {},
    config
  }))
  const queueCreator = new QueueCreator({
    channels: new Collection(merged),
    logger: new Logger(),
    options
  })
  queueCreator.configLoader.load = jest.fn().mockResolvedValue({
    site: 'movistarplus.es',
    url: () => 'https://fixture.invalid/schedule',
    parser: () => [],
    request: {
      method: 'GET',
      timeout: 1000,
      adapter
    }
  })

  const queue = await queueCreator.create()
  const item = queue.items().find(queueItem => queueItem.channel.site_id === 'newchannel')
  if (!item) throw new Error('Discovered channel was not added to the queue')
  expect(item.channel).toBeInstanceOf(Channel)

  const grabber = new EPGGrabber()
  await expect(grabber.grab(item.channel, item.date, item.config)).resolves.toEqual([])
  expect(adapter).toHaveBeenCalledTimes(1)
})
