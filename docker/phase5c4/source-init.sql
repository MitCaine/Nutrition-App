CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE TABLE qualification_transactions (
    sequence_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    transaction_id uuid NOT NULL UNIQUE,
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    category text NOT NULL CHECK (
        category IN (
            'daily_log_snapshot',
            'recipe_revision',
            'ocr_provenance',
            'control_authority',
            'recovery_boundary'
        )
    ),
    payload_digest text NOT NULL CHECK (payload_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE qualification_protected_roots (
    root_name text PRIMARY KEY,
    root_digest text NOT NULL CHECK (root_digest ~ '^[0-9a-f]{64}$'),
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE FUNCTION reject_qualification_history_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'qualification_history_immutable' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER trg_qualification_transactions_immutable
BEFORE UPDATE OR DELETE ON qualification_transactions
FOR EACH ROW EXECUTE FUNCTION reject_qualification_history_mutation();

INSERT INTO qualification_transactions(transaction_id, category, payload_digest)
VALUES
    ('00000000-0000-4000-8000-000000000101', 'daily_log_snapshot', repeat('1', 64)),
    ('00000000-0000-4000-8000-000000000102', 'recipe_revision', repeat('2', 64)),
    ('00000000-0000-4000-8000-000000000103', 'ocr_provenance', repeat('3', 64)),
    ('00000000-0000-4000-8000-000000000104', 'control_authority', repeat('4', 64));

INSERT INTO qualification_protected_roots(root_name, root_digest)
VALUES
    ('immutable_history', encode(digest(
        (
            SELECT string_agg(
                transaction_id::text || ':' || category || ':' || payload_digest,
                ',' ORDER BY sequence_id
            )
            FROM qualification_transactions
        ),
        'sha256'
    ), 'hex'));
