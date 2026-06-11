import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { login as apiLogin } from '../api/auth';
import { useAuth } from '../context/AuthContext';

export function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();

  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);

  const [emailError, setEmailError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [formError, setFormError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.body.className = 'auth-body';
    return () => { document.body.className = ''; };
  }, []);

  // Redirect if already logged in
  useEffect(() => {
    if (user) {
      navigate(user.role === 'admin' ? '/admin' : '/dashboard', { replace: true });
    }
  }, [user, navigate]);

  function fillAdminDemo() {
    if (emailRef.current) emailRef.current.value = 'admin@creditos.app';
    if (passwordRef.current) passwordRef.current.value = 'credits123';
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setFormError('');
    setEmailError('');
    setPasswordError('');

    const emailVal = emailRef.current?.value ?? '';
    const passwordVal = passwordRef.current?.value ?? '';

    const emailInput = emailRef.current;
    const emailOk = emailInput ? emailInput.validity.valid && emailVal.length > 0 : false;
    const passOk = passwordVal.length > 0;

    if (!emailOk) setEmailError('Enter a valid email address.');
    if (!passOk) setPasswordError('Password is required.');
    if (!emailOk || !passOk) return;

    setLoading(true);
    try {
      const data = await apiLogin(emailVal, passwordVal);
      login(data.access_token, data.user);
      navigate(data.user.role === 'admin' ? '/admin' : '/dashboard', { replace: true });
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { message?: string } } };
      setFormError(apiErr?.response?.data?.message ?? 'Invalid credentials.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="auth-card">
      <Link className="brand" to="/">
        <span className="brand-mark" />
        <span>CreditOS</span>
      </Link>
      <p className="eyebrow">Welcome back</p>
      <h1>Log in to your credit workspace.</h1>
      <p className="lead">Use a buyer or admin email to test role-based routing.</p>
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            defaultValue="buyer@acme.io"
            autoComplete="email"
            required
            ref={emailRef}
          />
          <span className="inline-error">{emailError}</span>
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            defaultValue="credits123"
            autoComplete="current-password"
            required
            ref={passwordRef}
          />
          <span className="inline-error">{passwordError}</span>
        </div>
        <button className="btn" type="submit" disabled={loading}>
          {loading ? <><span className="spinner" /> Logging in</> : 'Log in'}
        </button>
        <button className="btn-secondary" type="button" onClick={fillAdminDemo}>
          Use admin demo
        </button>
        <p className="inline-error">{formError}</p>
      </form>
      <p className="auth-switch">
        No account yet? <Link to="/signup">Sign up</Link>
      </p>
    </main>
  );
}
