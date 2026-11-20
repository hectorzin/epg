import type { Config } from '@netlify/edge-functions'

// OTT-TV downloads the full guide hundreds of times per hour and used 98% of the team's
// bandwidth. The `header` filter means this only runs for that client: others skip it entirely.
// Both public paths redirect to guides/guide.xml.gz on GitHub.
export default () =>
  new Response('Acceso a la guia no disponible para este cliente.\n', {
    status: 403,
    headers: { 'content-type': 'text/plain; charset=utf-8' }
  })

export const config: Config = {
  path: ['/guide.xml', '/guide.xml.gz'],
  header: { 'user-agent': '^OTT-TV/' }
}
