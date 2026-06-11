import { NavLink, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

interface AppNavProps {
  balance?: number;
}

export function AppNav({ balance }: AppNavProps) {
  const { user, logout } = useAuth();

  const buyerLinks = [
    { to: '/store', label: 'Store' },
    { to: '/dashboard', label: 'Dashboard' },
    { to: '/playground', label: 'Playground' },
  ];

  const adminLinks = [
    { to: '/admin', label: 'Packages' },
  ];

  const links = user?.role === 'admin' ? adminLinks : buyerLinks;

  return (
    <nav className="app-nav">
      <Link className="brand" to="/">
        <span className="brand-mark" />
        <span>CreditOS</span>
      </Link>
      <div className="nav-links">
        {links.map((link) => (
          <NavLink
            key={link.to}
            className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`}
            to={link.to}
          >
            {link.label}
          </NavLink>
        ))}
      </div>
      <div className="nav-spacer" />
      {user?.role !== 'admin' && balance !== undefined && (
        <span className="balance-pill">
          <span className="dot" />
          {new Intl.NumberFormat('en-US').format(balance)} credits
        </span>
      )}
      <div className="user-menu">
        <span className="avatar">{user?.initials ?? '?'}</span>
        <span className="role-chip">{user?.role ?? 'guest'}</span>
        <button className="logout-link" type="button" onClick={logout}>
          Logout
        </button>
      </div>
    </nav>
  );
}
