// GitHub serves guide.xml.gz as a gzip member. A transport Content-Encoding is
// already removed by fetch(); a file that is itself gzip still starts with 1f 8b.
export async function decodeGuideBody(bytes: Uint8Array): Promise<string> {
  if (bytes.length >= 2 && bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const payload = new ArrayBuffer(bytes.byteLength)
    new Uint8Array(payload).set(bytes)
    const stream = new Blob([payload]).stream().pipeThrough(new DecompressionStream('gzip'))
    return new Response(stream).text()
  }
  return new TextDecoder().decode(bytes)
}
