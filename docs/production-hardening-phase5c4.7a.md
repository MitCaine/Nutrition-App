# Phase 5C4.7a: promotion authorization and preactivation evidence

Phase 5C4.7a authorizes one exact route-switch intent and records the
authoritative evidence needed by a later target-activation stage. It does not
open either database for new production writes.

## Schema and write-fence boundary

Recovery validation, promotion authorization, and target-activation
authorization all bind application schema
`0020_immutable_provenance_enforcement`. Route switching and post-cutover
verification run while the source is frozen and the target remains
maintenance-closed under schema 0020. The activation authorization's signed
schema field is an evidence binding; it is not authority to execute a future
schema.

Phase 5C4.7a ends after an immutable activation-evidence binding has joined:

- the admitted `phase5c4_promotion_authorization_v2`;
- its one-use route-switch consumption and exact external-action intent;
- the successful immutable route observation;
- a passing immutable post-cutover receipt with the complete fixed check set;
- the admitted `phase5c4_target_activation_authorization_v2`.

The activation authorization remains unconsumed. There is no target-activation
request, target runtime-write grant, `open_production`, automatic cutback, or
emergency-close operation in this stage.

## Operator sequence

1. Provision the dedicated promotion verifier before upgrading the control
   database to `ops_0009_phase5c4_promotion_auth`.
2. Bootstrap or rotate only public Ed25519 key material through the migrator
   surface.
3. Export the canonical promotion statement and framed signing message. An
   external signer returns a raw detached signature; no Nutrition App command
   accepts a private key.
4. Verify and admit the signed promotion authorization through
   `nutrition_control_promotion_authorization_verifier`.
5. Request the route switch once through `request_route_switch_v1`. Commit the
   stored intent before an external executor changes routing.
6. Record the generic provider observation, then the exact independently
   collected route observation. Only a successful observation targeting the
   bound target may advance to `ENDPOINT_SWITCHED`.
7. Start post-cutover verification and record receipts. Failed receipts remain
   immutable evidence and cannot advance the workflow. A separate passing
   receipt must contain every fixed check and must still report the target as
   closed.
8. Admit the independently signed target-activation authorization. The wrapper
   reconstructs the complete chain from authoritative control rows and creates
   the immutable evidence binding.

Exact retries return the stored result. Changed request bytes, authorization
identity, nonce, command identity, observation bytes, or receipt bytes fail
closed and leave immutable conflict evidence where the relevant contract
defines it. Transient serialization and deadlock failures are bounded retries;
operators must reconcile the already stored external action after an ambiguous
post-commit failure rather than issue a second authorization.

## Rollback and Phase 5C4.7b

The control migration has an empty-only downgrade to the qualified v6
baseline. Any Phase 5C4.7a trust, authorization, consumption, observation,
receipt, binding, event, or conflict history blocks downgrade. Operators must
not delete or rewrite evidence to force rollback.

Application migration 0021 and target opening are Phase 5C4.7b work.
Phase 5C4.7b must define a separate execution-schema contract and may not
reinterpret a signed schema-0020 field as schema 0021. Before any open
transition can be committed, 5C4.7b must also provide and prove emergency-close
authority and behavior.
