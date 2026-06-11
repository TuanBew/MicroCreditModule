import { useEffect, useState, useRef } from 'react';
import { Link } from 'react-router-dom';
import { AppShell } from '../components/AppShell';
import { getWallet } from '../api/wallet';
import type { WalletData } from '../api/wallet';
import { runFeature } from '../api/features';
import { useToast } from '../components/Toast';

const creditsFormat = (n: number) => new Intl.NumberFormat('en-US').format(n);

interface FeaturePanelConfig {
  key: string;
  title: string;
  description: string;
  cost: number;
  actionLabel: string;
  renderAction: (disabled: boolean) => React.ReactNode;
  resultContent: React.ReactNode;
}

const FEATURE_CONFIGS: FeaturePanelConfig[] = [
  {
    key: 'image-generation',
    title: 'Image Generation',
    description: 'Generate campaign-ready visuals from a text prompt.',
    cost: 10,
    actionLabel: 'Generate · 10 credits',
    renderAction: (disabled) => (
      <div className="field">
        <label htmlFor="image-prompt">Prompt</label>
        <textarea
          id="image-prompt"
          defaultValue="A crisp product hero image for a SaaS launch campaign, blue interface glow, no people."
          disabled={disabled}
        />
      </div>
    ),
    resultContent: (
      <>
        <div className="mock-image">Generated image placeholder</div>
        <p className="muted">Credits deducted immediately. A ledger row is now available in Wallet.</p>
      </>
    ),
  },
  {
    key: 'auto-posting',
    title: 'Auto-Posting',
    description: 'Schedule an approved post to a connected destination.',
    cost: 250,
    actionLabel: 'Schedule · 250 credits',
    renderAction: (disabled) => (
      <>
        <div className="field">
          <label htmlFor="post-content">Post content</label>
          <textarea
            id="post-content"
            defaultValue="New launch assets are ready. Explore the campaign kit and pick your next channel."
            disabled={disabled}
          />
        </div>
        <div className="field">
          <label htmlFor="destination">Destination</label>
          <select id="destination" disabled={disabled}>
            <option>LinkedIn company page</option>
            <option>Product updates channel</option>
            <option>Customer newsletter queue</option>
          </select>
        </div>
      </>
    ),
    resultContent: (
      <>
        <h3>Post scheduled.</h3>
        <p className="muted">The destination queue received the draft and credits were deducted.</p>
      </>
    ),
  },
  {
    key: 'bulk-export',
    title: 'Bulk Export',
    description: 'Export generated assets and metadata in batches.',
    cost: 5,
    actionLabel: 'Export · 5 credits',
    renderAction: (disabled) => (
      <div className="field">
        <label htmlFor="export-format">Export format</label>
        <select id="export-format" disabled={disabled}>
          <option>CSV + asset links</option>
          <option>JSON manifest</option>
          <option>ZIP archive</option>
        </select>
      </div>
    ),
    resultContent: (
      <>
        <h3>Export prepared.</h3>
        <p className="muted">The batch file is ready and credits were deducted.</p>
      </>
    ),
  },
  {
    key: 'audience-insights',
    title: 'Audience Insights',
    description: 'Score campaign assets against saved audience segments.',
    cost: 80,
    actionLabel: 'Score · 80 credits',
    renderAction: (disabled) => (
      <div className="field">
        <label htmlFor="segment-select">Segment</label>
        <select id="segment-select" disabled={disabled}>
          <option>North America mid-market buyers</option>
          <option>Developer-tool evaluators</option>
          <option>Agency partner accounts</option>
        </select>
      </div>
    ),
    resultContent: (
      <>
        <h3>Audience score ready.</h3>
        <p className="muted">The segment fit summary is available and credits were deducted.</p>
      </>
    ),
  },
];

export function Playground() {
  const { showToast } = useToast();
  const [wallet, setWallet] = useState<WalletData | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState<Record<string, boolean>>({});
  const [results, setResults] = useState<Record<string, boolean>>({});
  const [loadError, setLoadError] = useState(false);
  const hasLoadedRef = useRef(false);

  async function loadWallet(initial = false) {
    try {
      const w = await getWallet();
      setWallet(w);
      if (initial) setLoadError(false);
    } catch {
      if (initial) setLoadError(true);
    }
  }

  useEffect(() => {
    if (!hasLoadedRef.current) {
      hasLoadedRef.current = true;
      setLoading(true);
      void loadWallet(true).finally(() => setLoading(false));
    }
  }, []);

  function getFeatureState(featureKey: string) {
    if (!wallet) return { owned: false, affordable: false };
    const feature = wallet.features.find((f) => f.key === featureKey);
    const owned = feature?.owned ?? false;
    const affordable = owned && (wallet.balance >= (feature?.cost ?? 0));
    return { owned, affordable };
  }

  async function handleRun(config: FeaturePanelConfig) {
    setRunning((prev) => ({ ...prev, [config.key]: true }));
    try {
      const result = await runFeature(config.key, {});
      setResults((prev) => ({ ...prev, [config.key]: true }));
      showToast(`${config.title} ran. ${config.cost} credits deducted.`, 'success');
      // Update local balance
      setWallet((prev) => prev ? { ...prev, balance: result.balance } : prev);
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { code?: string; message?: string }; status?: number } };
      const code = apiErr?.response?.data?.code;
      if (code === 'FEATURE_LOCKED') {
        showToast('Feature is not unlocked for your account.', 'error');
      } else if (code === 'INSUFFICIENT_CREDITS' || apiErr?.response?.status === 402) {
        showToast('Insufficient credits to run this feature.', 'error');
      } else {
        showToast(apiErr?.response?.data?.message ?? 'Failed to run feature.', 'error');
      }
    } finally {
      setRunning((prev) => ({ ...prev, [config.key]: false }));
      // Refresh wallet after any run attempt
      void loadWallet(false);
    }
  }

  return (
    <AppShell balance={wallet?.balance}>
      {loadError && (
        <p className="inline-error" style={{ marginBottom: 16 }}>
          Could not load feature data. Check your connection and refresh.
        </p>
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Feature Playground</p>
          <h1>Run gated features with clear access barriers.</h1>
          <p className="lead">Locked means no entitlement. Insufficient credits means entitlement exists, but the current balance cannot cover the per-use cost.</p>
        </div>
        <Link className="btn-secondary" to="/store">Top up or unlock</Link>
      </header>

      {loading ? (
        <section className="playground-grid">
          {FEATURE_CONFIGS.map((c) => (
            <div key={c.key} className="skeleton" />
          ))}
        </section>
      ) : (
        <section className="playground-grid">
          {FEATURE_CONFIGS.map((config) => {
            const { owned, affordable } = getFeatureState(config.key);
            const isRunning = running[config.key] ?? false;
            const hasResult = results[config.key] ?? false;

            let bandClass = 'access-band available';
            let bandTitle = 'Unlocked & affordable';
            let bandCopy = `${creditsFormat(wallet?.balance ?? 0)} credits available.`;

            if (!owned) {
              bandClass = 'access-band locked';
              bandTitle = 'Locked';
              bandCopy = `Unlock with a package that includes this feature.`;
            } else if (!affordable) {
              bandClass = 'access-band insufficient';
              bandTitle = 'Insufficient credits';
              bandCopy = `You own this feature, but need ${creditsFormat(config.cost)} credits to run it.`;
            }

            return (
              <article key={config.key} className="card feature-panel">
                <div className="panel-title">
                  <div>
                    <h2>{config.title}</h2>
                    <p className="muted">{config.description}</p>
                  </div>
                  <span className="credit-chip">{config.cost} credits</span>
                </div>

                <div className={bandClass}>
                  <div>
                    <strong>{bandTitle}</strong>
                    <span> {bandCopy}</span>
                  </div>
                  {!owned && (
                    <Link className="btn-secondary" to="/store">Go to Store</Link>
                  )}
                  {owned && !affordable && (
                    <Link className="btn-secondary" to="/store">Top up</Link>
                  )}
                </div>

                {owned && (
                  <div>
                    {config.renderAction(!affordable || isRunning)}
                    <button
                      className="btn"
                      type="button"
                      disabled={!affordable || isRunning}
                      onClick={() => handleRun(config)}
                      style={{ marginTop: 10 }}
                    >
                      {isRunning ? <><span className="spinner" /> Running</> : config.actionLabel}
                    </button>
                  </div>
                )}

                {hasResult && (
                  <div className="result-card is-visible">
                    {config.resultContent}
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}
    </AppShell>
  );
}
