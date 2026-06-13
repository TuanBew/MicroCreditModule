import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { signup as apiSignup } from '../api/auth';
import { useAuth } from '../context/AuthContext';

export function Signup() {
  const { login, user } = useAuth();
  const navigate = useNavigate();

  const emailRef = useRef<HTMLInputElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const confirmRef = useRef<HTMLInputElement>(null);

  const [emailError, setEmailError] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [confirmError, setConfirmError] = useState('');
  const [formError, setFormError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    document.body.className = 'auth-body';
    return () => { document.body.className = ''; };
  }, []);

  useEffect(() => {
    if (user) {
      navigate(user.role === 'admin' ? '/admin' : '/dashboard', { replace: true });
    }
  }, [user, navigate]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEmailError('');
    setPasswordError('');
    setConfirmError('');
    setFormError('');

    const emailVal = emailRef.current?.value ?? '';
    const passwordVal = passwordRef.current?.value ?? '';
    const confirmVal = confirmRef.current?.value ?? '';

    const emailInput = emailRef.current;
    const emailOk = emailInput ? emailInput.validity.valid && emailVal.length > 0 : false;
    const passOk = passwordVal.length >= 8;
    const matchOk = passwordVal === confirmVal && confirmVal.length > 0;

    if (!emailOk) setEmailError('Use a valid work email.');
    if (!passOk) setPasswordError('Password must be at least 8 characters.');
    if (!matchOk) setConfirmError('Passwords must match.');
    if (!emailOk || !passOk || !matchOk) return;

    setLoading(true);
    try {
      const data = await apiSignup(emailVal, passwordVal);
      login(data.user);
      navigate('/dashboard', { replace: true });
    } catch (err: unknown) {
      const apiErr = err as { response?: { data?: { message?: string } } };
      setFormError(apiErr?.response?.data?.message ?? 'Could not create account. Please try again.');
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
      <p className="eyebrow">Create workspace</p>
      <h1>Start with credits and unlocked capability.</h1>
      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            placeholder="you@company.com"
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
            placeholder="At least 8 characters"
            autoComplete="new-password"
            required
            ref={passwordRef}
          />
          <span className="inline-error">{passwordError}</span>
        </div>
        <div className="field">
          <label htmlFor="confirm">Confirm password</label>
          <input
            id="confirm"
            type="password"
            autoComplete="new-password"
            required
            ref={confirmRef}
          />
          <span className="inline-error">{confirmError}</span>
        </div>
        <button className="btn" type="submit" disabled={loading}>
          {loading ? <><span className="spinner" /> Creating</> : 'Create account'}
        </button>
        <p className="inline-error">{formError}</p>
      </form>
      <p className="auth-switch">
        Already have an account? <Link to="/login">Log in</Link>
      </p>
    </main>
  );
}
