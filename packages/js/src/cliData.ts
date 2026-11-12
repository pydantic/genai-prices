/* eslint-disable @typescript-eslint/restrict-template-expressions */
import { REMOTE_DATA_JSON_URL } from './api'

export async function downloadProviderData(): Promise<unknown> {
  const signal = AbortSignal.timeout(10_000)
  let onAbort: (() => void) | undefined
  const deadline = new Promise<never>((_resolve, reject) => {
    onAbort = () => {
      // eslint-disable-next-line prefer-promise-reject-errors -- AbortSignal.timeout supplies a TimeoutError.
      reject(signal.reason as Error)
    }
    signal.addEventListener('abort', onAbort, { once: true })
  })
  try {
    const download = async (): Promise<unknown> => {
      const response = await fetch(REMOTE_DATA_JSON_URL, { signal })
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }
      return response.json() as Promise<unknown>
    }
    // Native body reads can remain pending after abort; enforce the same deadline independently.
    return await Promise.race([download(), deadline])
  } finally {
    if (onAbort) signal.removeEventListener('abort', onAbort)
  }
}
