import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "cosmecitobot_session";
const SESSION_DURATION_SECONDS = 60 * 60 * 12;

type SessionPayload = { exp: number; v: 1 };

function secret() {
  const value = process.env.API_ADMIN_TOKEN;
  if (!value) throw new Error("API_ADMIN_TOKEN no está configurado.");
  return value;
}

function digest(value: string) {
  return createHmac("sha256", secret()).update(value).digest();
}

function equals(left: Buffer, right: Buffer) {
  return left.length === right.length && timingSafeEqual(left, right);
}

export function credentialsAreValid(username: string, password: string) {
  const expectedUsername = process.env.ADMIN_USERNAME;
  const expectedPassword = process.env.ADMIN_PASSWORD;
  if (!expectedUsername || !expectedPassword) return false;

  return equals(digest(username), digest(expectedUsername))
    && equals(digest(password), digest(expectedPassword));
}

function sign(payload: string) {
  return createHmac("sha256", secret()).update(payload).digest("base64url");
}

export function createSession() {
  const payload: SessionPayload = { exp: Date.now() + SESSION_DURATION_SECONDS * 1000, v: 1 };
  const encoded = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `${encoded}.${sign(encoded)}`;
}

export function hasValidSession(value: string | undefined) {
  if (!value) return false;
  const [encoded, signature, ...rest] = value.split(".");
  if (!encoded || !signature || rest.length || !equals(Buffer.from(signature), Buffer.from(sign(encoded)))) return false;

  try {
    const payload = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8")) as SessionPayload;
    return payload.v === 1 && Number.isFinite(payload.exp) && payload.exp > Date.now();
  } catch {
    return false;
  }
}

export const sessionCookieOptions = {
  httpOnly: true,
  maxAge: SESSION_DURATION_SECONDS,
  path: "/",
  sameSite: "strict" as const,
  secure: process.env.NODE_ENV === "production",
};
