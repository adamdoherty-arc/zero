const TOKEN_KEY = 'zero_api_token'

// Auto-set token from build-time env var.
// Always sync with the build token so a rebuild with a new token takes effect
// without requiring the user to clear localStorage manually.
const buildToken = import.meta.env.VITE_API_TOKEN
if (buildToken) {
  localStorage.setItem(TOKEN_KEY, buildToken)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

export function getAuthHeaders(): Record<string, string> {
  const token = getToken()
  if (token) {
    return { Authorization: `Bearer ${token}` }
  }
  return {}
}
