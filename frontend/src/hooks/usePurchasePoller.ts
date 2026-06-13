import { useCallback, useRef, useState } from 'react';
import type { TransactionStatus } from '../api/purchases';
import { getPurchaseStatus } from '../api/purchases';

type PollState = 'idle' | 'polling' | 'completed' | 'failed';

interface PollResult {
  state: PollState;
  status: TransactionStatus | null;
  start: (transactionId: string) => void;
  reset: () => void;
}

const POLL_INTERVAL_MS = 1500;
const MAX_POLLS = 40; // ~60s max (timer interval only; add per-request latency)

export function usePurchasePoller(): PollResult {
  const [state, setState] = useState<PollState>('idle');
  const [status, setStatus] = useState<TransactionStatus | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countRef = useRef(0);
  const abortedRef = useRef(false);

  const stop = useCallback(() => {
    abortedRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
  }, []);

  const reset = useCallback(() => {
    stop();
    abortedRef.current = false;
    setState('idle');
    setStatus(null);
    countRef.current = 0;
  }, [stop]);

  const poll = useCallback(async (transactionId: string) => {
    if (abortedRef.current) return;

    if (countRef.current >= MAX_POLLS) {
      setState('failed');
      setStatus({
        transaction_id: transactionId,
        status: 'failed',
        failure_reason: 'Timed out waiting for confirmation.',
      });
      return;
    }

    try {
      const result = await getPurchaseStatus(transactionId);
      if (abortedRef.current) return;
      setStatus(result);
      if (result.status === 'completed') {
        setState('completed');
        return;
      }
      if (result.status === 'failed') {
        setState('failed');
        return;
      }
    } catch {
      // network hiccup — keep polling
    }

    countRef.current += 1;
    if (!abortedRef.current) {
      timerRef.current = setTimeout(() => void poll(transactionId), POLL_INTERVAL_MS);
    }
  }, []);

  const start = useCallback(
    (transactionId: string) => {
      reset();
      setState('polling');
      void poll(transactionId);
    },
    [reset, poll],
  );

  return { state, status, start, reset };
}
