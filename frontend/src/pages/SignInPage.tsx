import { SignIn } from "@clerk/react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

export default function SignInPage() {
  const navigate = useNavigate();
  const [dummyEmail, setDummyEmail] = useState("demo@jansahay.gov.in");
  const [dummyPassword, setDummyPassword] = useState("demo123");
  const [showGoogleAuth, setShowGoogleAuth] = useState(false);

  const handleDummyLogin = (e: React.FormEvent) => {
    e.preventDefault();
    const token = `guest_${Date.now()}`;
    localStorage.setItem("guest_auth_token", token);
    localStorage.setItem("guest_user_name", dummyEmail.split("@")[0] || "Demo User");
    navigate("/chat");
  };

  const handleQuickGuest = () => {
    localStorage.setItem("guest_auth_token", "guest_demo_user");
    localStorage.setItem("guest_user_name", "Guest Citizen");
    navigate("/chat");
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-[#fbf9f5] px-4 py-12">
      <div className="w-full max-w-md space-y-6">
        {/* Header */}
        <div className="text-center">
          <img
            src="/goverment.png"
            alt="JanSahay"
            className="mx-auto h-12 w-12 rounded-full object-cover shadow-sm"
          />
          <h1 className="mt-3 text-2xl font-bold text-zinc-900">
            JanSahay Access & Sign In
          </h1>
          <p className="mt-1 text-sm text-zinc-600">
            Use dummy credentials, guest login, or Google sign-in
          </p>
        </div>

        {/* Card 1: Dummy Credentials & Instant Guest Access */}
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl">
          <div className="mb-4 flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-100 text-lg">
              🔑
            </span>
            <div>
              <h2 className="text-base font-bold text-zinc-900">
                Dummy Credentials / Guest Login
              </h2>
              <p className="text-xs text-zinc-500">
                Instant access without Google account
              </p>
            </div>
          </div>

          <form onSubmit={handleDummyLogin} className="space-y-3">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-600">
                Username / Email
              </label>
              <input
                type="text"
                value={dummyEmail}
                onChange={(e) => setDummyEmail(e.target.value)}
                className="mt-1 w-full rounded-xl border border-zinc-300 bg-zinc-50 px-3.5 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-emerald-500"
                placeholder="demo@jansahay.gov.in"
                required
              />
            </div>

            <div>
              <label className="block text-xs font-semibold uppercase tracking-wider text-zinc-600">
                Password
              </label>
              <input
                type="password"
                value={dummyPassword}
                onChange={(e) => setDummyPassword(e.target.value)}
                className="mt-1 w-full rounded-xl border border-zinc-300 bg-zinc-50 px-3.5 py-2 text-sm text-zinc-900 outline-none focus:ring-2 focus:ring-emerald-500"
                placeholder="••••••••"
                required
              />
            </div>

            <button
              type="submit"
              className="mt-2 w-full rounded-xl bg-zinc-900 py-2.5 text-sm font-semibold text-white transition-all hover:bg-zinc-800 active:scale-[0.99]"
            >
              Log In with Dummy Credentials
            </button>
          </form>

          <div className="relative my-4 flex items-center justify-center">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-zinc-200" />
            </div>
            <span className="relative bg-white px-3 text-xs font-semibold uppercase tracking-wider text-zinc-400">
              Or
            </span>
          </div>

          <button
            type="button"
            onClick={handleQuickGuest}
            className="w-full rounded-xl border border-emerald-300 bg-emerald-50 py-2.5 text-sm font-bold text-emerald-800 transition-all hover:bg-emerald-100 active:scale-[0.99]"
          >
            ⚡ Continue as Guest (Instant Access)
          </button>
        </div>

        {/* Card 2: Google Sign-In option */}
        <div className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-xl text-center">
          <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Prefer Google Sign In?
          </p>
          
          {!showGoogleAuth ? (
            <button
              type="button"
              onClick={() => setShowGoogleAuth(true)}
              className="mt-3 w-full rounded-xl border border-zinc-300 bg-white py-2.5 text-sm font-semibold text-zinc-800 transition-all hover:bg-zinc-50"
            >
              Sign In with Google Account
            </button>
          ) : (
            <div className="mt-4 flex justify-center">
              <SignIn routing="hash" />
            </div>
          )}

        </div>
      </div>
    </div>
  );
}
