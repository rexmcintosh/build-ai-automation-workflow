import { chunkText } from './chunk'

export class Telegram {
  constructor(private token: string) {}

  async call(
    method: string,
    params: Record<string, unknown> = {},
    timeoutMs = 30_000,
  ): Promise<any> {
    let res: Response
    try {
      res = await fetch(`https://api.telegram.org/bot${this.token}/${method}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(params),
        signal: AbortSignal.timeout(timeoutMs),
      })
    } catch {
      // Bun's fetch errors carry a `path` property holding the full URL — which
      // contains the token. Never let the original error escape.
      throw new Error(`telegram ${method}: network failure`)
    }
    const body: any = await res.json()
    if (!body.ok) {
      // Never include the URL (contains the token) in errors.
      throw new Error(`telegram ${method} failed: ${body.error_code} ${body.description}`)
    }
    return body.result
  }

  async getUpdates(offset: number, timeoutSec: number): Promise<any[]> {
    // Long poll: allow the server's full hold time plus slack before aborting.
    return this.call(
      'getUpdates',
      { offset, timeout: timeoutSec, allowed_updates: ['message'] },
      (timeoutSec + 15) * 1000,
    )
  }

  async send(chatId: number, threadId: number | undefined, text: string): Promise<void> {
    for (const chunk of chunkText(text)) {
      await this.call('sendMessage', {
        chat_id: chatId,
        text: chunk,
        ...(threadId !== undefined ? { message_thread_id: threadId } : {}),
      })
    }
  }

  async createTopic(chatId: number, name: string): Promise<number> {
    const topic = await this.call('createForumTopic', { chat_id: chatId, name: name.slice(0, 128) })
    return topic.message_thread_id
  }

  async renameAndClose(chatId: number, threadId: number, name: string): Promise<void> {
    await this.call('editForumTopic', { chat_id: chatId, message_thread_id: threadId, name: name.slice(0, 128) })
    await this.call('closeForumTopic', { chat_id: chatId, message_thread_id: threadId })
  }
}
