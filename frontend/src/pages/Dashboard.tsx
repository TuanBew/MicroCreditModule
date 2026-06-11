import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AppShell } from '../components/AppShell';
import { getWallet, getPurchases, getLedger } from '../api/wallet';
import type { WalletData, Purchase, LedgerEntry } from '../api/wallet';

const money = (cents: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(cents / 100);

const credits = (n: number) =>
  new Intl.NumberFormat('en-US').format(n);

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
}

export function Dashboard() {
  const [wallet, setWallet] = useState<WalletData | null>(null);
  const [purchases, setPurchases] = useState<Purchase[]>([]);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [activeTab, setActiveTab] = useState<'purchases' | 'ledger'>('purchases');

  useEffect(() => {
    async function load() {
      setLoading(true);
      setLoadError(false);
      try {
        const [w, p, l] = await Promise.all([getWallet(), getPurchases(), getLedger()]);
        setWallet(w);
        setPurchases(p);
        setLedger(l);
      } catch {
        setLoadError(true);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  return (
    <AppShell balance={wallet?.balance}>
      {loadError && (
        <p className="inline-error" style={{ marginBottom: 16 }}>
          Could not load wallet data. Check your connection and refresh.
        </p>
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Dashboard / Wallet</p>
          <h1>Your credit balance and permanent feature access.</h1>
          <p className="lead">Balance is metered and changes with every purchase or feature run. Entitlements stay unlocked once purchased.</p>
        </div>
        <Link className="btn" to="/store">Buy credits</Link>
      </header>

      <section className="wallet-hero">
        <article className="balance-hero">
          <p className="eyebrow" style={{ color: 'oklch(84% 0.09 82)' }}>Available balance</p>
          <div className="balance-number">
            {loading ? <span className="spinner" /> : credits(wallet?.balance ?? 0)}
          </div>
          <p>Credits ready for gated workflows. Every run creates a ledger entry.</p>
          <Link className="btn" to="/store">Top up balance</Link>
        </article>

        <article className="card card-pad">
          <div className="panel-title">
            <h2>Entitlements</h2>
            <span className="status-pill success">Permanent unlocks</span>
          </div>
          {loading ? (
            <div className="skeleton" />
          ) : (
            <div className="entitlement-grid">
              {(wallet?.features ?? []).map((feature) => (
                <div key={feature.key} className={`entitlement${feature.owned ? '' : ' locked'}`}>
                  <h3>{feature.name}</h3>
                  <p className="muted">
                    {feature.owned
                      ? `${credits(feature.cost)} credits per use`
                      : `Locked · unlock with ${feature.unlock_package_name}`}
                  </p>
                  <Link
                    className={feature.owned ? 'btn-secondary' : 'btn-ghost'}
                    to={feature.owned ? '/playground' : '/store'}
                  >
                    {feature.owned ? 'Open in Playground' : 'Unlock'}
                  </Link>
                </div>
              ))}
            </div>
          )}
        </article>
      </section>

      <section className="card card-pad" style={{ marginTop: 18 }}>
        <div className="panel-title">
          <div>
            <h2>History</h2>
            <p className="muted">Purchases and credit activity are separated so finance and product usage tell different stories.</p>
          </div>
          <div className="tabs" role="tablist">
            <button
              className={`tab${activeTab === 'purchases' ? ' is-active' : ''}`}
              type="button"
              onClick={() => setActiveTab('purchases')}
            >
              Purchase history
            </button>
            <button
              className={`tab${activeTab === 'ledger' ? ' is-active' : ''}`}
              type="button"
              onClick={() => setActiveTab('ledger')}
            >
              Credit activity
            </button>
          </div>
        </div>

        {loading && <div className="skeleton" />}

        <div className="tab-panel" hidden={activeTab !== 'purchases'}>
          {!loading && purchases.length === 0 ? (
            <div className="empty-state">
              <h3>No purchases yet</h3>
              <p className="muted">Choose a package in the Store to activate credits and feature access.</p>
              <Link className="btn" to="/store">Browse packages</Link>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Package</th>
                    <th>Amount paid</th>
                    <th>Credits</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {purchases.map((p) => (
                    <tr key={p.id}>
                      <td>{formatDate(p.created_at)}</td>
                      <td>{p.package_name}</td>
                      <td>{money(p.amount_cents)}</td>
                      <td>{credits(p.credits_granted)}</td>
                      <td>{p.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="tab-panel" hidden={activeTab !== 'ledger'}>
          {!loading && ledger.length === 0 ? (
            <div className="empty-state">
              <h3>No credit movement yet</h3>
              <p className="muted">Purchases and feature runs will appear here as signed ledger entries.</p>
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Description</th>
                    <th>Amount</th>
                    <th>Resulting balance</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.map((entry) => (
                    <tr key={entry.id}>
                      <td>{formatDate(entry.created_at)}</td>
                      <td>{entry.description}</td>
                      <td className={entry.delta > 0 ? 'amount-pos' : 'amount-neg'}>
                        {entry.delta > 0 ? '+' : ''}{credits(entry.delta)}
                      </td>
                      <td>{credits(entry.balance_after)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>
    </AppShell>
  );
}
