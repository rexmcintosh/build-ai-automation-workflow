import { chunkText } from './chunk'

export class Telegram {
  constructor(private token: string) {}

  async call(method: string, params: Record<string, unknown> = {}): Promise<any> {
    const res = await fetch(`https://api.telegram.org/bot${this.token}/${method}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(params),
    })
    const body: any = await res.json()
    if (!body.ok) {
      // Never include the URL (contains the token) in errors.
      throw new Error(`telegram ${method} failed: ${body.error_code} ${body.description}`)
    }
    return body.result
  }

  async getUpdates(offset: number, timeoutSec: number): Promise<any[]> {
    return this.call('getUpdates', { offset, timeout: timeoutSec, allowed_updates: ['message'] })
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
