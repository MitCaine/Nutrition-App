CREATE TABLE provider_state (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    route_state text NOT NULL CHECK (route_state IN ('source', 'target', 'unknown')),
    source_writable boolean NOT NULL,
    target_fenced boolean NOT NULL,
    provider_revision bigint NOT NULL CHECK (provider_revision >= 1),
    updated_at timestamptz NOT NULL
);

CREATE TABLE provider_operations (
    operation_id uuid PRIMARY KEY,
    request_digest text NOT NULL CHECK (request_digest ~ '^[0-9a-f]{64}$'),
    action text NOT NULL CHECK (
        action IN ('route_source', 'route_target', 'restore_source', 'fence_target')
    ),
    result text NOT NULL CHECK (
        result IN ('applied', 'partial', 'unknown', 'conflicting')
    ),
    provider_revision bigint NOT NULL,
    observed_at timestamptz NOT NULL
);

INSERT INTO provider_state(
    route_state, source_writable, target_fenced, provider_revision, updated_at
) VALUES ('target', false, true, 1, clock_timestamp());

CREATE FUNCTION apply_provider_operation_v1(
    requested_operation_id uuid,
    requested_digest text,
    requested_action text,
    fault_mode text
)
RETURNS jsonb
LANGUAGE plpgsql
AS $$
DECLARE
    existing provider_operations%ROWTYPE;
    current_state provider_state%ROWTYPE;
    result_value text := 'applied';
BEGIN
    IF requested_digest !~ '^[0-9a-f]{64}$'
       OR requested_action NOT IN (
           'route_source', 'route_target', 'restore_source', 'fence_target'
       )
       OR fault_mode NOT IN (
           'none', 'unknown_before_commit', 'partial_after_commit',
           'conflicting_after_commit'
       ) THEN
        RAISE EXCEPTION 'provider_request_invalid' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO existing
    FROM provider_operations
    WHERE operation_id = requested_operation_id
    FOR UPDATE;
    IF FOUND THEN
        IF existing.request_digest <> requested_digest
           OR existing.action <> requested_action THEN
            RAISE EXCEPTION 'provider_operation_conflict' USING ERRCODE = '23505';
        END IF;
        RETURN jsonb_build_object(
            'operation_id', existing.operation_id,
            'provider_revision', existing.provider_revision,
            'result', existing.result,
            'replay', true
        );
    END IF;

    SELECT * INTO current_state FROM provider_state WHERE singleton FOR UPDATE;
    IF fault_mode = 'unknown_before_commit' THEN
        result_value := 'unknown';
    ELSE
        IF requested_action = 'route_source' THEN
            UPDATE provider_state
            SET route_state = CASE
                    WHEN fault_mode = 'conflicting_after_commit' THEN 'target'
                    WHEN fault_mode = 'partial_after_commit' THEN 'unknown'
                    ELSE 'source'
                END,
                provider_revision = provider_revision + 1,
                updated_at = clock_timestamp()
            WHERE singleton;
        ELSIF requested_action = 'route_target' THEN
            UPDATE provider_state
            SET route_state = CASE
                    WHEN fault_mode = 'conflicting_after_commit' THEN 'source'
                    WHEN fault_mode = 'partial_after_commit' THEN 'unknown'
                    ELSE 'target'
                END,
                source_writable = false,
                provider_revision = provider_revision + 1,
                updated_at = clock_timestamp()
            WHERE singleton;
        ELSIF requested_action = 'fence_target' THEN
            UPDATE provider_state
            SET target_fenced = fault_mode <> 'conflicting_after_commit',
                provider_revision = provider_revision + 1,
                updated_at = clock_timestamp()
            WHERE singleton;
        ELSIF requested_action = 'restore_source' THEN
            IF current_state.route_state <> 'source' OR NOT current_state.target_fenced THEN
                RAISE EXCEPTION 'source_restore_order_invalid' USING ERRCODE = '55000';
            END IF;
            UPDATE provider_state
            SET source_writable = fault_mode <> 'conflicting_after_commit',
                provider_revision = provider_revision + 1,
                updated_at = clock_timestamp()
            WHERE singleton;
        END IF;
        result_value := CASE
            WHEN fault_mode = 'partial_after_commit' THEN 'partial'
            WHEN fault_mode = 'conflicting_after_commit' THEN 'conflicting'
            ELSE 'applied'
        END;
    END IF;

    SELECT * INTO current_state FROM provider_state WHERE singleton;
    INSERT INTO provider_operations(
        operation_id, request_digest, action, result, provider_revision, observed_at
    ) VALUES (
        requested_operation_id, requested_digest, requested_action, result_value,
        current_state.provider_revision, clock_timestamp()
    );
    RETURN jsonb_build_object(
        'operation_id', requested_operation_id,
        'provider_revision', current_state.provider_revision,
        'result', result_value,
        'replay', false
    );
END;
$$;

CREATE FUNCTION read_provider_state_v1()
RETURNS jsonb
LANGUAGE sql
STABLE
AS $$
    SELECT jsonb_build_object(
        'last_operation_id', operation.operation_id,
        'last_request_digest', operation.request_digest,
        'last_result', operation.result,
        'provider_revision', state.provider_revision,
        'route_state', state.route_state,
        'source_writable', state.source_writable,
        'target_fenced', state.target_fenced,
        'updated_at', to_char(
            state.updated_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        )
    )
    FROM provider_state state
    LEFT JOIN LATERAL (
        SELECT operation_id, request_digest, result
        FROM provider_operations
        ORDER BY observed_at DESC, operation_id
        LIMIT 1
    ) operation ON true
    WHERE state.singleton
$$;
