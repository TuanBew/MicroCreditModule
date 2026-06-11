import { useEffect, useState } from 'react';
import { AppShell } from '../components/AppShell';
import { listPackages, createPackage, updatePackage, deletePackage } from '../api/packages';
import type { Package } from '../api/packages';
import { listFeatures } from '../api/features';
import type { Feature } from '../api/features';
import { useToast } from '../components/Toast';

const money = (cents: number) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(cents / 100);

const creditsFormat = (n: number) => new Intl.NumberFormat('en-US').format(n);

interface PackageFormState {
  name: string;
  description: string;
  price_cents: string;
  credits: string;
  features: string[];
  active: boolean;
}

const emptyForm = (): PackageFormState => ({
  name: '',
  description: '',
  price_cents: '',
  credits: '',
  features: [],
  active: true,
});

export function Admin() {
  const { showToast } = useToast();
  const [packages, setPackages] = useState<Package[]>([]);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);

  // Package modal
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<PackageFormState>(emptyForm());
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // Delete modal
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  async function loadData(initial = false) {
    setLoading(true);
    if (initial) setLoadError(false);
    try {
      const [pkgs, feats] = await Promise.all([listPackages(), listFeatures()]);
      setPackages(pkgs);
      setFeatures(feats);
    } catch {
      if (initial) setLoadError(true);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData(true);
  }, []);

  function openCreate() {
    setEditingId(null);
    setForm(emptyForm());
    setFormErrors({});
    setModalOpen(true);
    document.body.classList.add('modal-open');
  }

  function openEdit(pkg: Package) {
    setEditingId(pkg.id);
    setForm({
      name: pkg.name,
      description: pkg.description,
      price_cents: String(pkg.price_cents),
      credits: String(pkg.credits),
      features: [...pkg.features],
      active: pkg.active,
    });
    setFormErrors({});
    setModalOpen(true);
    document.body.classList.add('modal-open');
  }

  function closeModal() {
    setModalOpen(false);
    setDeleteTarget(null);
    document.body.classList.remove('modal-open');
  }

  function toggleFeature(key: string) {
    setForm((prev) => ({
      ...prev,
      features: prev.features.includes(key)
        ? prev.features.filter((f) => f !== key)
        : [...prev.features, key],
    }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const errors: Record<string, string> = {};
    if (!form.name.trim()) errors.name = 'Name is required.';
    const price = Number(form.price_cents);
    const creds = Number(form.credits);
    if (!(price > 0)) errors.price_cents = 'Enter a numeric price in cents.';
    if (!(creds > 0)) errors.credits = 'Enter a numeric credit amount.';
    if (form.features.length === 0) errors.features = 'Choose at least one feature entitlement.';
    if (Object.keys(errors).length > 0) { setFormErrors(errors); return; }

    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        description: form.description.trim(),
        price_cents: price,
        credits: creds,
        features: form.features,
        active: form.active,
      };
      if (editingId) {
        await updatePackage(editingId, payload);
      } else {
        await createPackage(payload);
      }
      closeModal();
      await loadData();
      showToast('Package saved. Catalog updated.', 'success');
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { message?: string } } };
      showToast(apiErr?.response?.data?.message ?? 'Failed to save package.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deletePackage(deleteTarget);
      closeModal();
      await loadData();
      showToast('Package deactivated. Purchase history preserved.', 'success');
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { message?: string } } };
      showToast(apiErr?.response?.data?.message ?? 'Failed to delete package.', 'error');
    } finally {
      setDeleting(false);
    }
  }

  return (
    <AppShell>
      {loadError && (
        <p className="inline-error" style={{ marginBottom: 16 }}>
          Could not load catalog data. Check your connection and refresh.
        </p>
      )}
      <header className="page-header">
        <div>
          <p className="eyebrow">Admin catalog</p>
          <h1>Manage credit packages without touching customer usage history.</h1>
          <p className="lead">Create, edit, deactivate, and safely remove catalog entries. Existing purchase records remain preserved.</p>
        </div>
        <button className="btn" type="button" onClick={openCreate}>New package</button>
      </header>

      <section className="card card-pad admin-layout">
        <div className="toolbar">
          <div>
            <h2>Packages</h2>
            <p className="muted">Feature entitlements are sourced from the fixed feature catalog below.</p>
          </div>
        </div>

        {loading && <div className="skeleton" />}

        {!loading && packages.length === 0 && (
          <div className="empty-state">
            <h3>No packages yet</h3>
            <p className="muted">Create the first package so buyers can purchase credits and unlock features.</p>
            <button className="btn" type="button" onClick={openCreate}>Create package</button>
          </div>
        )}

        {!loading && packages.length > 0 && (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Price</th>
                  <th>Credits</th>
                  <th>Unlocked features</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {packages.map((pkg) => (
                  <tr key={pkg.id}>
                    <td>{pkg.name}</td>
                    <td>{money(pkg.price_cents)}</td>
                    <td>{creditsFormat(pkg.credits)}</td>
                    <td>
                      <div className="feature-chips">
                        {pkg.features.map((fKey) => {
                          const feat = features.find((f) => f.key === fKey);
                          return (
                            <span key={fKey} className="chip">
                              {feat?.name ?? fKey}
                            </span>
                          );
                        })}
                      </div>
                    </td>
                    <td>
                      <span className={`status-pill ${pkg.active ? 'active' : 'inactive'}`}>
                        {pkg.active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td>
                      <button className="btn-ghost" type="button" onClick={() => openEdit(pkg)}>Edit</button>
                      {' '}
                      <button
                        className="danger-btn"
                        type="button"
                        onClick={() => { setDeleteTarget(pkg.id); document.body.classList.add('modal-open'); }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card card-pad" style={{ marginTop: 18 }}>
        <div className="panel-title">
          <div>
            <h2>Feature catalog</h2>
            <p className="muted">Reference-only feature list used by admins when building packages.</p>
          </div>
          <span className="status-pill active">Optional support view</span>
        </div>
        <div className="grid-3">
          {features.map((feature) => (
            <article key={feature.key} className="entitlement">
              <h3>{feature.name}</h3>
              <p className="muted">{feature.key} · {feature.cost} credits per use</p>
              <p>{feature.description}</p>
            </article>
          ))}
        </div>
      </section>

      {/* Package create/edit modal */}
      {modalOpen && (
        <div className="modal-backdrop is-visible" role="dialog" aria-modal="true" aria-labelledby="package-modal-title">
          <section className="modal wide">
            <div className="modal-header">
              <div>
                <p className="eyebrow">Catalog form</p>
                <h2 id="package-modal-title">{editingId ? 'Edit package' : 'New package'}</h2>
              </div>
              <button className="icon-btn" type="button" aria-label="Close" onClick={closeModal}>×</button>
            </div>
            <form className="stack" onSubmit={handleSave} noValidate>
              <div className="field">
                <label htmlFor="pkg-name">Name</label>
                <input
                  id="pkg-name"
                  value={form.name}
                  onChange={(e) => setForm((p) => ({ ...p, name: e.target.value }))}
                  required
                />
                <span className="inline-error">{formErrors.name}</span>
              </div>
              <div className="field">
                <label htmlFor="pkg-description">Description</label>
                <textarea
                  id="pkg-description"
                  value={form.description}
                  onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                />
              </div>
              <div className="form-row">
                <div className="field">
                  <label htmlFor="pkg-price">Price (cents)</label>
                  <input
                    id="pkg-price"
                    inputMode="numeric"
                    value={form.price_cents}
                    onChange={(e) => setForm((p) => ({ ...p, price_cents: e.target.value }))}
                    required
                  />
                  <span className="inline-error">{formErrors.price_cents}</span>
                </div>
                <div className="field">
                  <label htmlFor="pkg-credits">Credit amount</label>
                  <input
                    id="pkg-credits"
                    inputMode="numeric"
                    value={form.credits}
                    onChange={(e) => setForm((p) => ({ ...p, credits: e.target.value }))}
                    required
                  />
                  <span className="inline-error">{formErrors.credits}</span>
                </div>
              </div>
              <div className="field">
                <label>Features unlocked</label>
                <div className="checkbox-list">
                  {features.map((feat) => (
                    <label key={feat.key} className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={form.features.includes(feat.key)}
                        onChange={() => toggleFeature(feat.key)}
                      />
                      {feat.name} · {feat.cost} credits/use
                    </label>
                  ))}
                </div>
                <span className="inline-error">{formErrors.features}</span>
              </div>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={form.active}
                  onChange={(e) => setForm((p) => ({ ...p, active: e.target.checked }))}
                />
                Active package
              </label>
              <div className="modal-actions">
                <button className="btn-secondary" type="button" onClick={closeModal}>Cancel</button>
                <button className="btn" type="submit" disabled={saving}>
                  {saving ? <><span className="spinner" /> Saving</> : 'Save package'}
                </button>
              </div>
            </form>
          </section>
        </div>
      )}

      {/* Delete confirmation modal */}
      {deleteTarget && !modalOpen && (
        <div className="modal-backdrop is-visible" role="dialog" aria-modal="true" aria-labelledby="delete-title">
          <section className="modal">
            <div className="modal-header">
              <div>
                <p className="eyebrow">Safe removal</p>
                <h2 id="delete-title">Deactivate package?</h2>
                <p className="muted">Existing purchase history and customer entitlements stay preserved. The package will be hidden from future purchases.</p>
              </div>
              <button className="icon-btn" type="button" aria-label="Close" onClick={closeModal}>×</button>
            </div>
            <div className="modal-actions">
              <button className="btn-secondary" type="button" onClick={closeModal}>Cancel</button>
              <button className="danger-btn" type="button" onClick={handleDelete} disabled={deleting}>
                {deleting ? <><span className="spinner" /> Deactivating</> : 'Deactivate package'}
              </button>
            </div>
          </section>
        </div>
      )}
    </AppShell>
  );
}
