import { lazy, Suspense, useState, type FormEvent } from "react";
import { BrowserRouter, HashRouter, Navigate, NavLink, Route, Routes } from "react-router-dom";
import { ErrorBox, Field } from "./components/ui";
import { DEMO } from "./lib/api";
import { AuthProvider, useAuth } from "./lib/auth";
import { ROLE_LABEL } from "./lib/i18n";
import { OrderDetailPage, OrdersPage } from "./pages/Orders";
import { OwnerDetailPage, OwnersPage } from "./pages/Owners";
import { ResultPage } from "./pages/Result";
import { RunPage, RunsPage } from "./pages/Runs";
import { SamplesPage } from "./pages/Samples";
import { UsersPage } from "./pages/Users";

// ECharts is only loaded with the trends page.
const TrendsPage = lazy(() => import("./pages/Trends").then((m) => ({ default: m.TrendsPage })));

function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await login(username, password);
    } catch {
      setError("Nieprawidłowa nazwa użytkownika lub hasło");
    }
  };
  return (
    <form className="card login" onSubmit={submit}>
      <h1>qcdb – logowanie</h1>
      <Field label="Użytkownik">
        <input name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </Field>
      <Field label="Hasło">
        <input name="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      </Field>
      <ErrorBox error={error} />
      <p>
        <button type="submit">Zaloguj</button>
      </p>
    </form>
  );
}

function Shell() {
  const { me, checked, logout, isAdmin } = useAuth();
  if (!checked) return null;
  if (!me) return <Login />;
  return (
    <>
      {DEMO && (
        <div className="demo-banner">
          Wersja demonstracyjna tylko do odczytu, z fikcyjnymi danymi testowymi. Widok jak dla roli bioinformatyka.
        </div>
      )}
      <div className="layout">
        <nav className="nav">
          <div className="brand">qcdb</div>
          <NavLink to="/probki">Próbki</NavLink>
          <NavLink to="/przebiegi">Przebiegi</NavLink>
          <NavLink to="/trendy">Trendy</NavLink>
          <NavLink to="/zleceniodawcy">Zleceniodawcy</NavLink>
          <NavLink to="/zlecenia">Zlecenia</NavLink>
          {isAdmin && <NavLink to="/uzytkownicy">Użytkownicy</NavLink>}
          <div className="user">
            {me.username} ({ROLE_LABEL[me.role]})
            {!DEMO && (
              <p>
                <button className="secondary" onClick={() => void logout()}>
                  Wyloguj
                </button>
              </p>
            )}
          </div>
        </nav>
        <main className="main">
          <Routes>
            <Route path="/" element={<Navigate to="/probki" replace />} />
            <Route path="/probki" element={<SamplesPage />} />
            <Route path="/wyniki/:id" element={<ResultPage />} />
            <Route path="/przebiegi" element={<RunsPage />} />
            <Route path="/przebiegi/:code" element={<RunPage />} />
            <Route path="/trendy" element={<Suspense fallback={<p className="muted">Wczytywanie…</p>}><TrendsPage /></Suspense>} />
            <Route path="/zleceniodawcy" element={<OwnersPage />} />
            <Route path="/zleceniodawcy/:id" element={<OwnerDetailPage />} />
            <Route path="/zlecenia" element={<OrdersPage />} />
            <Route path="/zlecenia/:id" element={<OrderDetailPage />} />
            <Route path="/uzytkownicy" element={<UsersPage />} />
            <Route path="*" element={<p>Nie znaleziono strony.</p>} />
          </Routes>
        </main>
      </div>
    </>
  );
}

export function App() {
  // GitHub Pages cannot rewrite deep links, so the demo uses hash URLs.
  const Router = DEMO ? HashRouter : BrowserRouter;
  return (
    <AuthProvider>
      <Router>
        <Shell />
      </Router>
    </AuthProvider>
  );
}
