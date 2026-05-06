import client from "./client"
import type { User } from "../types"

export interface LoginPayload { username: string; password: string }
export interface RegisterPayload { username: string; email: string; password: string }
export interface TokenResponse { user: User; token_type: string }
export interface OIDCLoginResponse { authorization_url: string }

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/login", payload)
  return data
}

export async function register(payload: RegisterPayload): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/register", payload)
  return data
}

export async function logout(): Promise<void> {
  await client.post("/auth/logout")
}

export async function me(): Promise<User> {
  const { data } = await client.get<User>("/auth/me")
  return data
}

export async function refresh(): Promise<TokenResponse> {
  const { data } = await client.post<TokenResponse>("/auth/refresh")
  return data
}

export async function oidcLogin(): Promise<OIDCLoginResponse> {
  const { data } = await client.get<OIDCLoginResponse>("/auth/oidc/login")
  return data
}
