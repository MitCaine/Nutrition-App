import * as Crypto from "expo-crypto";

export function createClientRequestId(): string {
  return Crypto.randomUUID();
}
