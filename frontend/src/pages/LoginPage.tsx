import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ArrowRight, Eye, EyeOff } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError, apiFetch } from "../lib/api";
import { setToken } from "../lib/auth";
import { VibiFace } from "../components/VibiFace";

interface LoginResponse {
  token: string;
}

export function LoginPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const location = useLocation();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError("");
    try {
      const { token } = await apiFetch<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ nombre: name, contraseña: password }),
      });
      queryClient.clear();
      setToken(token);
      const destination = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(destination, { replace: true });
    } catch (reason) {
      setError(
        reason instanceof ApiError ? reason.message : "No se pudo abrir la sesión",
      );
    } finally {
      setPending(false);
    }
  };

  return (
    <main className="login-stage">
      <section className="login-identity" aria-label="Vibi local">
        <div className="login-vibi" aria-hidden="true">
          <VibiFace state="idle" perfil="companion" />
        </div>
        <div className="login-identity-copy">
          <p className="eyebrow">TU ESPACIO LOCAL</p>
          <h2>Una sola Vibi.<br />Todo tu trabajo.</h2>
          <p>Habla, organiza y ejecuta desde el mismo lugar.</p>
        </div>
      </section>

      <section className="login-card" aria-labelledby="login-title">
        <p className="eyebrow">Canal privado</p>
        <h1 id="login-title">Vibi</h1>
        <p className="login-intro">
          Tus planes, proyectos y conversaciones, en el mismo círculo.
        </p>

        <form onSubmit={submit} className="login-form">
          <label>
            <span>Nombre</span>
            <input
              autoComplete="username"
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </label>
          <label>
            <span>Contraseña</span>
            <span className="password-field">
              <input
                type={showPassword ? "text" : "password"}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
              <button
                type="button"
                className="icon-button"
                onClick={() => setShowPassword((visible) => !visible)}
                aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
              >
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </span>
          </label>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="primary-button login-submit" disabled={pending}>
            <span>{pending ? "Abriendo…" : "Entrar"}</span>
            <ArrowRight size={18} />
          </button>
        </form>
      </section>
    </main>
  );
}
