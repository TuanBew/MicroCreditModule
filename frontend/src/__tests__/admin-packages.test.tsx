import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { Admin } from '../pages/Admin';
import { AuthProvider } from '../context/AuthContext';
import { ToastProvider } from '../components/Toast';
import type { Package } from '../api/packages';
import type { Feature } from '../api/features';

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
vi.mock('../api/packages', () => ({
  listPackages: vi.fn(),
  createPackage: vi.fn(),
  updatePackage: vi.fn(),
  deletePackage: vi.fn(),
}));

vi.mock('../api/features', () => ({
  listFeatures: vi.fn(),
}));

import { listPackages, createPackage, updatePackage, deletePackage } from '../api/packages';
import { listFeatures } from '../api/features';

const mockedListPackages = vi.mocked(listPackages);
const mockedCreatePackage = vi.mocked(createPackage);
const mockedUpdatePackage = vi.mocked(updatePackage);
const mockedDeletePackage = vi.mocked(deletePackage);
const mockedListFeatures = vi.mocked(listFeatures);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------
const FEATURES: Feature[] = [
  { key: 'summarize', name: 'Summarize', description: 'Summarize text', cost: 10, unlock_package_name: 'starter' },
  { key: 'translate', name: 'Translate', description: 'Translate text', cost: 20, unlock_package_name: 'pro' },
];

const PACKAGES: Package[] = [
  {
    id: 'pkg-1',
    slug: 'starter',
    name: 'Starter',
    badge: 'S',
    description: 'Entry-level package',
    price_cents: 999,
    credits: 100,
    active: true,
    features: ['summarize'],
  },
  {
    id: 'pkg-2',
    slug: 'pro',
    name: 'Pro',
    badge: 'P',
    description: 'Professional package',
    price_cents: 2999,
    credits: 500,
    active: false,
    features: ['summarize', 'translate'],
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Seed localStorage so AuthProvider exposes an admin user. */
function seedAdminAuth() {
  localStorage.setItem(
    'creditos:user',
    JSON.stringify({ id: 'u1', email: 'admin@test.com', role: 'admin', initials: 'AT' }),
  );
  localStorage.setItem('creditos:token', 'fake-token');
}

function renderAdmin() {
  seedAdminAuth();
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ToastProvider>
          <Admin />
        </ToastProvider>
      </AuthProvider>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  document.body.classList.remove('modal-open');

  // Default: resolve immediately with fixture data
  mockedListPackages.mockResolvedValue(PACKAGES);
  mockedListFeatures.mockResolvedValue(FEATURES);
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('Admin packages page', () => {
  // 1. Table renders package rows
  it('renders package rows in the table', async () => {
    renderAdmin();
    expect(await screen.findByText('Starter')).toBeInTheDocument();
    expect(screen.getByText('Pro')).toBeInTheDocument();
    // Check price formatting ($9 for 999 cents, $29 for 2999 cents — maximumFractionDigits:0 rounds $9.99→$10, $29.99→$30)
    expect(screen.getByText('$10')).toBeInTheDocument();
    expect(screen.getByText('$30')).toBeInTheDocument();
    // Credits
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('500')).toBeInTheDocument();
  });

  // 2. Active / inactive status pills
  it('renders active and inactive status pills', async () => {
    renderAdmin();
    expect(await screen.findByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Inactive')).toBeInTheDocument();

    const activePill = screen.getByText('Active');
    expect(activePill).toHaveClass('status-pill', 'active');

    const inactivePill = screen.getByText('Inactive');
    expect(inactivePill).toHaveClass('status-pill', 'inactive');
  });

  // 3. Feature chips render
  it('renders feature chips for each package', async () => {
    renderAdmin();
    await screen.findByText('Starter');
    // Starter has 'summarize' → should render chip "Summarize"
    const chips = screen.getAllByText('Summarize');
    expect(chips.length).toBeGreaterThanOrEqual(1);
    // Pro has both
    expect(screen.getAllByText('Translate').length).toBeGreaterThanOrEqual(1);
  });

  // 4. Loading skeleton
  it('renders loading skeleton while data is loading', () => {
    // Never resolve the promises so we stay in loading state
    mockedListPackages.mockReturnValue(new Promise(() => {}));
    mockedListFeatures.mockReturnValue(new Promise(() => {}));
    renderAdmin();
    expect(document.querySelector('.skeleton')).toBeInTheDocument();
  });

  // 5. Empty state
  it('renders empty state when no packages exist', async () => {
    mockedListPackages.mockResolvedValue([]);
    renderAdmin();
    expect(await screen.findByText('No packages yet')).toBeInTheDocument();
    expect(screen.getByText('Create package')).toBeInTheDocument();
  });

  // 6. Create modal validation
  it('validates required fields in the create modal', async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText('Starter');

    // Open the create modal
    await user.click(screen.getByText('New package'));
    expect(screen.getByText('New package', { selector: 'h2' })).toBeInTheDocument();

    // Submit empty form
    await user.click(screen.getByText('Save package'));

    // All validation errors should appear
    expect(screen.getByText('Name is required.')).toBeInTheDocument();
    expect(screen.getByText('Enter a numeric price in cents.')).toBeInTheDocument();
    expect(screen.getByText('Enter a numeric credit amount.')).toBeInTheDocument();
    expect(screen.getByText('Choose at least one feature entitlement.')).toBeInTheDocument();

    // API should NOT have been called
    expect(mockedCreatePackage).not.toHaveBeenCalled();
  });

  // 7. Edit modal pre-fills values
  it('pre-fills package values when editing', async () => {
    const user = userEvent.setup();
    renderAdmin();
    await screen.findByText('Starter');

    // Click "Edit" on the first package row
    const editButtons = screen.getAllByText('Edit');
    await user.click(editButtons[0]);

    expect(screen.getByText('Edit package')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveValue('Starter');
    expect(screen.getByLabelText('Price (cents)')).toHaveValue('999');
    expect(screen.getByLabelText('Credit amount')).toHaveValue('100');
  });

  // 8a. Save calls create endpoint for new packages
  it('calls createPackage on save for a new package', async () => {
    const user = userEvent.setup();
    mockedCreatePackage.mockResolvedValue({
      ...PACKAGES[0],
      id: 'pkg-new',
      name: 'New Pkg',
    });

    renderAdmin();
    await screen.findByText('Starter');

    await user.click(screen.getByText('New package'));

    await user.type(screen.getByLabelText('Name'), 'New Pkg');
    await user.type(screen.getByLabelText('Price (cents)'), '1500');
    await user.type(screen.getByLabelText('Credit amount'), '200');

    // Check a feature
    const checkboxes = screen.getAllByRole('checkbox');
    // First checkbox in the feature list (Summarize)
    const featureCheckbox = checkboxes.find(
      (cb) => cb.closest('label')?.textContent?.includes('Summarize'),
    );
    expect(featureCheckbox).toBeTruthy();
    await user.click(featureCheckbox!);

    await user.click(screen.getByText('Save package'));

    await waitFor(() => {
      expect(mockedCreatePackage).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'New Pkg',
          price_cents: 1500,
          credits: 200,
          features: ['summarize'],
        }),
      );
    });
  });

  // 8b. Save calls updatePackage for existing packages
  it('calls updatePackage on save for an edited package', async () => {
    const user = userEvent.setup();
    mockedUpdatePackage.mockResolvedValue(PACKAGES[0]);

    renderAdmin();
    await screen.findByText('Starter');

    const editButtons = screen.getAllByText('Edit');
    await user.click(editButtons[0]);

    const nameInput = screen.getByLabelText('Name');
    await user.clear(nameInput);
    await user.type(nameInput, 'Starter Plus');

    await user.click(screen.getByText('Save package'));

    await waitFor(() => {
      expect(mockedUpdatePackage).toHaveBeenCalledWith(
        'pkg-1',
        expect.objectContaining({ name: 'Starter Plus' }),
      );
    });
  });

  // 9. Deactivate calls DELETE endpoint
  it('calls deletePackage when deactivating a package', async () => {
    const user = userEvent.setup();
    mockedDeletePackage.mockResolvedValue(undefined);

    renderAdmin();
    await screen.findByText('Starter');

    // Click "Delete" on first row
    const deleteButtons = screen.getAllByText('Delete');
    await user.click(deleteButtons[0]);

    // Confirm dialog should appear
    expect(await screen.findByText('Deactivate package?')).toBeInTheDocument();
    await user.click(screen.getByText('Deactivate package'));

    await waitFor(() => {
      expect(mockedDeletePackage).toHaveBeenCalledWith('pkg-1');
    });
  });

  // 10. Feature catalog panel renders
  it('renders the feature catalog panel with all features', async () => {
    renderAdmin();
    await screen.findByText('Starter');

    expect(screen.getByText('Feature catalog')).toBeInTheDocument();
    // Feature entries in the catalog section
    const catalogSection = screen.getByText('Feature catalog').closest('section')!;
    expect(within(catalogSection).getByText('Summarize')).toBeInTheDocument();
    expect(within(catalogSection).getByText('Translate')).toBeInTheDocument();
    expect(within(catalogSection).getByText(/10 credits per use/)).toBeInTheDocument();
    expect(within(catalogSection).getByText(/20 credits per use/)).toBeInTheDocument();
  });

  // Bonus: Load error state
  it('shows error message when data fails to load', async () => {
    mockedListPackages.mockRejectedValue(new Error('Network error'));
    mockedListFeatures.mockRejectedValue(new Error('Network error'));

    renderAdmin();

    expect(
      await screen.findByText('Could not load catalog data. Check your connection and refresh.'),
    ).toBeInTheDocument();
  });
});
