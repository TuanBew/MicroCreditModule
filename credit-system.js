const CreditOS = (() => {
  const STORE = 'creditos:state:v3';
  const defaults = {
    role: 'user',
    user: { initials: 'RB', email: 'riley@northstar.ai' },
    credits: 32,
    ownedFeatures: ['image-generation', 'auto-posting', 'bulk-export'],
    purchases: [
      { date: '2026-06-02', package: 'Creator Pack', amount: 49, credits: 500, status: 'completed' },
      { date: '2026-05-21', package: 'Starter Pack', amount: 19, credits: 150, status: 'completed' }
    ],
    ledger: [
      { date: '2026-06-10 09:42', description: '−10 — Image generation', amount: -10, balance: 32 },
      { date: '2026-06-09 15:20', description: '−75 — Bulk export', amount: -75, balance: 42 },
      { date: '2026-06-02 14:18', description: '+500 — Creator Pack purchase', amount: 500, balance: 117 },
      { date: '2026-05-29 16:04', description: '−33 — Image generation batch', amount: -33, balance: -383 },
      { date: '2026-05-21 11:08', description: '+150 — Starter Pack purchase', amount: 150, balance: -350 }
    ]
  };

  const features = {
    'image-generation': { name: 'Image Generation', cost: 10, unlock: 'Creator Pack', description: 'Generate campaign-ready visuals from a text prompt.' },
    'auto-posting': { name: 'Auto-Posting', cost: 250, unlock: 'Growth Pack', description: 'Schedule approved posts to connected channels.' },
    'bulk-export': { name: 'Bulk Export', cost: 5, unlock: 'Starter Pack', description: 'Export generated assets and metadata in batches.' },
    'audience-insights': { name: 'Audience Insights', cost: 80, unlock: 'Enterprise Pack', description: 'Score campaign assets against saved audience segments.' }
  };

  const packages = [
    { id: 'starter', name: 'Starter Pack', badge: 'Entry', description: 'A small credit refill for occasional gated workflows.', price: 19, credits: 150, features: ['bulk-export'], active: true },
    { id: 'creator', name: 'Creator Pack', badge: 'Owned', description: 'Unlock image generation and keep a healthy credit buffer.', price: 49, credits: 500, features: ['image-generation', 'bulk-export'], active: true },
    { id: 'growth', name: 'Growth Pack', badge: 'Best value', description: 'Adds automation entitlements for teams running weekly campaigns.', price: 129, credits: 1500, features: ['image-generation', 'auto-posting', 'bulk-export'], active: true },
    { id: 'enterprise', name: 'Enterprise Pack', badge: 'Governance', description: 'Adds audience intelligence for teams operating across segments.', price: 299, credits: 2500, features: ['audience-insights', 'auto-posting', 'bulk-export'], active: true }
  ];

  function read() {
    try { return { ...defaults, ...JSON.parse(localStorage.getItem(STORE) || '{}') }; }
    catch (_) { return { ...defaults }; }
  }

  function write(next) {
    localStorage.setItem(STORE, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent('creditos:update', { detail: next }));
    return next;
  }

  function update(mutator) {
    const state = read();
    mutator(state);
    return write(state);
  }

  function money(value) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
  }

  function number(value) {
    return new Intl.NumberFormat('en-US').format(value);
  }

  function todayStamp() {
    return new Intl.DateTimeFormat('en-CA', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date());
  }

  function showToast(message, type = 'success') {
    let region = document.querySelector('.toast-region');
    if (!region) {
      region = document.createElement('div');
      region.className = 'toast-region';
      region.setAttribute('aria-live', 'polite');
      document.body.appendChild(region);
    }
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    region.appendChild(toast);
    setTimeout(() => toast.remove(), 3600);
  }

  function setLoading(button, isLoading, label) {
    if (!button) return;
    if (isLoading) {
      button.dataset.originalLabel = button.textContent.trim();
      button.disabled = true;
      const spinner = document.createElement('span');
      spinner.className = 'spinner';
      spinner.setAttribute('aria-hidden', 'true');
      button.replaceChildren(spinner, document.createTextNode(label || 'Working'));
    } else {
      button.disabled = false;
      button.textContent = button.dataset.originalLabel || button.textContent;
    }
  }

  function makeEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text !== undefined) el.textContent = text;
    return el;
  }

  function initShell(active = 'dashboard', role = 'user') {
    const state = read();
    const isAdmin = role === 'admin';
    const nav = document.querySelector('[data-app-nav]');
    if (!nav) return;
    const links = isAdmin
      ? [{ href: 'admin-packages.html', key: 'packages', label: 'Packages' }]
      : [
          { href: 'store.html', key: 'store', label: 'Store' },
          { href: 'dashboard-wallet.html', key: 'dashboard', label: 'Dashboard' },
          { href: 'playground.html', key: 'playground', label: 'Playground' }
        ];

    nav.replaceChildren();
    const brand = makeEl('a', 'brand');
    brand.href = 'credit-app.html';
    brand.setAttribute('aria-label', 'CreditOS home');
    brand.append(makeEl('span', 'brand-mark'), makeEl('span', '', 'CreditOS'));

    const navLinks = makeEl('div', 'nav-links');
    links.forEach((link) => {
      const anchor = makeEl('a', `nav-link ${link.key === active ? 'is-active' : ''}`, link.label);
      anchor.href = link.href;
      navLinks.appendChild(anchor);
    });

    nav.append(brand, navLinks, makeEl('div', 'nav-spacer'));
    if (!isAdmin) {
      const balance = makeEl('span', 'balance-pill');
      const amount = makeEl('span', '');
      amount.dataset.creditBalance = '';
      balance.append(makeEl('span', 'dot'), amount, document.createTextNode(' credits'));
      nav.appendChild(balance);
    }

    const userMenu = makeEl('div', 'user-menu');
    userMenu.append(makeEl('span', 'avatar', isAdmin ? 'AM' : state.user.initials), makeEl('span', 'role-chip', isAdmin ? 'Admin' : 'User'));
    const logout = makeEl('a', 'logout-link', 'Logout');
    logout.href = 'login.html';
    userMenu.appendChild(logout);
    nav.appendChild(userMenu);

    paintBalance();
    window.addEventListener('creditos:update', paintBalance);
  }

  function paintBalance() {
    const state = read();
    document.querySelectorAll('[data-credit-balance]').forEach((el) => { el.textContent = number(state.credits); });
  }

  function addPurchase(pkg) {
    return update((state) => {
      const newlyUnlocked = pkg.features.filter((feature) => !state.ownedFeatures.includes(feature));
      state.credits += pkg.credits;
      state.ownedFeatures = Array.from(new Set([...state.ownedFeatures, ...pkg.features]));
      state.purchases.unshift({ date: new Date().toISOString().slice(0, 10), package: pkg.name, amount: pkg.price, credits: pkg.credits, status: 'completed' });
      state.ledger.unshift({ date: todayStamp(), description: `+${pkg.credits} — ${pkg.name} purchase`, amount: pkg.credits, balance: state.credits });
      state.lastUnlocked = newlyUnlocked;
    });
  }

  function spendCredits(featureKey) {
    const feature = features[featureKey];
    return update((state) => {
      state.credits -= feature.cost;
      state.ledger.unshift({ date: todayStamp(), description: `−${feature.cost} — ${feature.name}`, amount: -feature.cost, balance: state.credits });
    });
  }

  function hasFeature(key) { return read().ownedFeatures.includes(key); }
  function canAfford(key) { return read().credits >= features[key].cost; }

  return { defaults, features, packages, read, write, update, money, number, showToast, setLoading, initShell, paintBalance, addPurchase, spendCredits, hasFeature, canAfford };
})();
