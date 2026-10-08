-- State the API keeps (the API itself is stateless): one row per /v1/query call, and user
-- feedback on those answers. Written and read by t2s_app (default privileges from 0004).

CREATE TABLE app.queries (
    query_id    uuid             PRIMARY KEY,
    user_id     text             NOT NULL,
    question    text             NOT NULL,
    status      text             NOT NULL CHECK (status IN (
                    'answered', 'cannot_answer', 'blocked', 'rejected', 'failed', 'error')),
    sql         text,
    attempts    smallint         NOT NULL DEFAULT 0,
    row_count   integer,
    total_ms    double precision,
    total_tokens integer,
    cost_usd    numeric(12, 6),
    created_at  timestamptz      NOT NULL DEFAULT now()
);
CREATE INDEX queries_user_created_idx ON app.queries (user_id, created_at DESC);

CREATE TABLE app.feedback (
    feedback_id bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    query_id    uuid        NOT NULL REFERENCES app.queries (query_id) ON DELETE CASCADE,
    user_id     text        NOT NULL,
    rating      smallint    NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     text        CHECK (char_length(comment) <= 2000),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (query_id, user_id)  -- one rating per user and answer; resubmitting replaces it
);

COMMENT ON TABLE app.queries IS
    'Audit log of questions asked through the API: who, what, outcome, SQL, timings and cost. Contains user-written text: treat as personal data.';
COMMENT ON TABLE app.feedback IS
    'User ratings (1-5) and optional comments on answers, keyed by app.queries.query_id.';
