import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { AppShell } from '../components/AppShell';
import { listPackages } from '../api/packages';
import type { Package } from '../api/packages';
import { createPurchase } from '../api/purchases';
import { getWallet } from '../api/wallet';
import { useToast } from '../components/Toast';

const money = (cents: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(cents / 100);

const credits = (n: number) =>
  new Intl.NumberFormat('en-US').format(n);

export function Store() {
  const { showToast } = useToast();
  const [packages, setPackages] = useState<Package[]>([]);
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState<number | undefined>(undefined);
  const [ownedFeatures, setOwnedFeatures] = useState<string[]>([]);
  const [loadError, setLoadError] = useState(false);

  // Modal state
  const [selectedPkg, setSelectedPkg] = useState<Package | null>(null);
  const [purchasing, setPurchasing] = useState(false);
  const [purchaseSuccess, setPurchaseSuccess] = useState<string | null>(null);
  const [purchaseError, setPurchaseError] = useState('');
  const [newBalance, setNewBalance] = useState<number | null>(null);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setLoadError(false);
      try {
        const [pkgs, wallet] = await Promise.all([listPackages(), getWallet()]);
        setPackages(pkgs.filter((p) => p.active));
        setBalance(wallet.balance);
        setOwnedFeatures(wallet.features.filter((f) => f.owned).map((f) => f.key));
      } catch {
        setLoadError(true);
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, []);

  function openModal(pkg: Package) {
    setSelectedPkg(pkg);
    setPurchaseSuccess(null);
    setPurchaseError('');
    setNewBalance(null);
    document.body.classList.add('modal-open');
  }

  function closeModal() {
    setSelectedPkg(null);
    document.body.classList.remove('modal-open');
  }

  async function handlePurchase() {
    if (!selectedPkg) return;
    setPurchasing(true);
    setPurchaseError('');
    try {
      const result = await createPurchase(selectedPkg.id);
      setNewBalance(result.balance);
      setBalance(result.balance);
      setOwnedFeatures(result.entitlements);
      setPurchaseSuccess(`New balance: ${credits(result.balance)} credits. ${selectedPkg.name} entitlements are now active forever.`);
      showToast(`${selectedPkg.name} purchased. Balance updated.`, 'success');
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { message?: string } } };
      setPurchaseError(apiErr?.response?.data?.message ?? 'Purchase failed. Please try again.');
    } finally {
      setPurchasing(false);
    }
  }

  const allFeaturesOwned = (pkg: Package) =>
    pkg.features.length > 0 && pkg.features.every((f) => ownedFeatures.includes(f));

  return (
    <AppShell balance={balance}>
      {loadError && (
        <p className="inline-error" style={{ marginBottom: 16 }}>
          Could not load store data. Check your connection and refresh.
        </p>
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Store</p>
          <h1>Choose a package and start creating with gated features.</h1>
          <p className="lead">Repurchase any owned package to add credits. New feature entitlements stay unlocked permanently after purchase.</p>
        </div>
      </header>

      {loading && (
        <section className="grid-3">
          <div className="skeleton" />
          <div className="skeleton" />
          <div className="skeleton" />
        </section>
      )}

      {!loading && packages.length === 0 && (
        <section className="empty-state">
          <h2>No packages available</h2>
          <p className="muted">Ask an admin to activate a package catalog before buyers can top up.</p>
        </section>
      )}

      {!loading && packages.length > 0 && (
        <section className="grid-3 package-grid" aria-label="Available packages">
          {packages.map((pkg) => {
            const allOwned = allFeaturesOwned(pkg);
            return (
              <article
                key={pkg.id}
                className={`card package-card${pkg.badge?.toLowerCase() === 'popular' ? ' featured' : ''}`}
              >
                <div className="package-top">
                  <div>
                    <span className="badge">{pkg.badge}</span>
                    <h2>{pkg.name}</h2>
                    <p className="muted">{pkg.description}</p>
                  </div>
                  <div className="price">{money(pkg.price_cents)}</div>
                </div>
                <span className="credit-chip">{credits(pkg.credits)} credits</span>
                <div className="feature-list">
                  {pkg.features.map((fKey) => (
                    <div key={fKey} className="feature-line">
                      <span className="feature-name">
                        <span className="feature-icon">✦</span>
                        {fKey.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                      </span>
                      <span className={ownedFeatures.includes(fKey) ? 'owned' : 'new-unlock'}>
                        {ownedFeatures.includes(fKey) ? 'Owned' : 'New'}
                      </span>
                    </div>
                  ))}
                </div>
                <button className="btn" type="button" onClick={() => openModal(pkg)}>
                  {allOwned ? `Buy again — adds ${credits(pkg.credits)} credits` : 'Purchase'}
                </button>
              </article>
            );
          })}
        </section>
      )}

      {/* Checkout modal */}
      {selectedPkg && (
        <div className="modal-backdrop is-visible" role="dialog" aria-modal="true" aria-labelledby="checkout-title">
          <section className="modal wide">
            <div className="modal-header">
              <div>
                <p className="eyebrow">Simulated checkout</p>
                <h2 id="checkout-title">Confirm purchase</h2>
                <p className="muted">No real payment is processed in this prototype.</p>
              </div>
              <button className="icon-btn" type="button" aria-label="Close" onClick={closeModal}>×</button>
            </div>
            <div className="grid-2">
              <div className="card card-pad">
                <h3>Order summary</h3>
                <p className="muted">{selectedPkg.name}</p>
                <div className="summary-row">
                  <span>Price</span>
                  <strong>{money(selectedPkg.price_cents)}</strong>
                </div>
                <div className="summary-row">
                  <span>Credits granted</span>
                  <strong>{credits(selectedPkg.credits)}</strong>
                </div>
                <div className="feature-list">
                  {selectedPkg.features.map((fKey) => (
                    <div key={fKey} className="feature-line">
                      <span className="feature-name">
                        {fKey.replace(/-/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())}
                      </span>
                      <span className={ownedFeatures.includes(fKey) ? 'owned' : 'new-unlock'}>
                        {ownedFeatures.includes(fKey) ? 'Already owned' : 'New unlock'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="card card-pad">
                <h3>Mock payment</h3>
                <p className="muted">Use the confirm button to preview processing, success, balance updates, and unlocked features.</p>
                <div className="field">
                  <label>Demo card</label>
                  <input value="4242 4242 4242 4242" aria-label="Demo card" readOnly />
                </div>
                <div className="modal-actions">
                  <button className="btn-secondary" type="button" onClick={closeModal}>Cancel</button>
                  <button
                    className="btn"
                    type="button"
                    onClick={handlePurchase}
                    disabled={purchasing || purchaseSuccess !== null}
                  >
                    {purchasing ? <><span className="spinner" /> Processing</> : `Pay ${money(selectedPkg.price_cents)}`}
                  </button>
                </div>
                {purchaseSuccess && (
                  <div className="success-state is-visible">
                    <h3>Purchase complete.</h3>
                    <p>{purchaseSuccess}</p>
                    <p>
                      <Link to="/playground" onClick={closeModal}>Go to Playground</Link>
                      {' · '}
                      <Link to="/dashboard" onClick={closeModal}>View Wallet</Link>
                    </p>
                    {newBalance !== null && (
                      <p className="muted">Balance updated to {credits(newBalance)} credits.</p>
                    )}
                  </div>
                )}
                {purchaseError && <p className="inline-error">{purchaseError}</p>}
              </div>
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
