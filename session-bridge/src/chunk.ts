export function chunkText(text: string, limit = 4096): string[] {
  if (text.length === 0) return []
  if (text.length <= limit) return [text]
  const chunks: string[] = []
  let current = ''
  for (const para of text.split('\n\n')) {
    const candidate = current === '' ? para : `${current}\n\n${para}`
    if (candidate.length <= limit) {
      current = candidate
      continue
    }
    if (current !== '') chunks.push(current)
    let rest = para
    while (rest.length > limit) {
      chunks.push(rest.slice(0, limit))
      rest = rest.slice(limit)
    }
    current = rest
  }
  if (current !== '') chunks.push(current)
  return chunks
}
