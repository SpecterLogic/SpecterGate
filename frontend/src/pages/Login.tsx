import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, Eye, EyeOff, KeyRound, Loader2, LockKeyhole, ShieldCheck, UserRound, Waypoints } from "lucide-react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Brand } from "../components/Layout";

export default function Login() {
  const { admin, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [requires2FA, setRequires2FA] = useState(false);
  const [otpCode, setOtpCode] = useState("");

  useEffect(() => {
    if (admin) navigate("/", { replace: true });
  }, [admin, navigate]);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
        try {
      await login(username.trim(), password, otpCode.trim() || undefined);
      navigate("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && (err.message === "2FA_REQUIRED" || err.status === 403)) {
        setRequires2FA(true);
        setError("لطفاً کد ۶ رقمی یا کد بازیابی دومرحله‌ای را وارد کنید.");
      } else {
        setError(err instanceof ApiError ? err.message : "اتصال به سرور برقرار نشد.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <div className="login-glow login-glow-a" />
      <div className="login-glow login-glow-b" />

      <section className="login-story">
        <Brand />
        <div className="story-copy">
          <span className="story-badge">
            <span className="pulse-dot" />
            کنترل کامل زیرساخت
          </span>
          <h1>
            یک پنل،
            <br />
            <span>همهٔ مسیرها.</span>
          </h1>
          <p>
            کاربران، اینباندها، نودها و مصرف ترافیک را در یک فضای کاری یکپارچه مدیریت کنید؛ با هستهٔ Xray و لینک‌های
            اشتراک چندپروتکلی.
          </p>
          <div className="story-features">
            <div>
              <ShieldCheck size={20} />
              <span>
                <strong>چندپروتکلی</strong>
                <small>VLESS · VMess · Trojan · Shadowsocks</small>
              </span>
            </div>
            <div>
              <Waypoints size={20} />
              <span>
                <strong>مدیریت چندنودی</strong>
                <small>سلامت، مصرف و کلید اختصاصی هر نود</small>
              </span>
            </div>
            <div>
              <KeyRound size={20} />
              <span>
                <strong>اشتراک هوشمند</strong>
                <small>خروجی Xray و Clash با یک لینک</small>
              </span>
            </div>
          </div>
        </div>
        <div className="story-footer">
          <span>SpecterGate Panel</span>
          <span>v0.1.0</span>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-card-head">
            <span className="login-icon">
              <LockKeyhole size={24} />
            </span>
            <div>
              <h2>ورود به پنل</h2>
              <p>برای ادامه، اطلاعات مدیریت خود را وارد کنید.</p>
            </div>
          </div>

          <form onSubmit={handleSubmit} className="login-form">
            <label className="login-field">
              <span>نام کاربری</span>
              <div className="login-input-wrap">
                <UserRound size={18} />
                <input
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="admin"
                  autoComplete="username"
                  autoFocus
                  required
                  dir="ltr"
                />
              </div>
            </label>
            <label className="login-field">
              <span>رمز عبور</span>
              <div className="login-input-wrap">
                <LockKeyhole size={18} />
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                  dir="ltr"
                />
                <button type="button" onClick={() => setShowPassword((value) => !value)} aria-label="نمایش رمز عبور">
                  {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                </button>
              </div>
            </label>
            {requires2FA && (
              <label className="login-field">
                <span>کد تأیید دومرحله‌ای (TOTP یا کد بازیابی)</span>
                <div className="login-input-wrap">
                  <ShieldCheck size={18} />
                  <input
                    value={otpCode}
                    onChange={(event) => setOtpCode(event.target.value)}
                    placeholder="۱۲۳۴۵۶ یا XXXX-XXXX"
                    autoFocus
                    required
                    dir="ltr"
                  />
                </div>
              </label>
            )}

            {error && <div className="login-error">{error}</div>}

            <button type="submit" className="login-submit" disabled={submitting}>
              {submitting ? <Loader2 className="spin" size={19} /> : <ArrowLeft size={19} />}
              <span>{submitting ? "در حال ورود..." : "ورود به فضای کاری"}</span>
            </button>
          </form>

          <div className="login-note">
            <ShieldCheck size={16} />
            <span>نشست شما با توکن امن محافظت می‌شود. رمز پیش‌فرض را پس از اولین ورود تغییر دهید.</span>
          </div>
        </div>
        <p className="login-copyright">ساخته‌شده برای کنترل کامل، بدون وابستگی به سرویس خارجی.</p>
      </section>
    </div>
  );
}
