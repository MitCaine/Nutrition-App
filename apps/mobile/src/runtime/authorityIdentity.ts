export const LOCAL_AUTHORITY_SCOPE_PREFIX = "local:";

export type RuntimeAuthorityIdentity = Readonly<{
  kind: "remote" | "local";
  recoveryScope: string;
}>;

/** Guard the namespace reserved for a later local runtime without creating one. */
export function remoteAuthorityIdentity(recoveryScope: string): RuntimeAuthorityIdentity {
  if (!recoveryScope || recoveryScope.startsWith(LOCAL_AUTHORITY_SCOPE_PREFIX)) {
    throw new Error("Remote runtime authority scope collides with the reserved local namespace.");
  }
  return Object.freeze({ kind: "remote", recoveryScope });
}

export function isReservedLocalAuthorityScope(scope: string): boolean {
  return scope.startsWith(LOCAL_AUTHORITY_SCOPE_PREFIX);
}
