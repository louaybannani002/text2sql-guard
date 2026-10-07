"""Function and cast-type allowlists for generated SQL, in sqlglot's own vocabulary.

sqlglot maps many Postgres functions to typed nodes (``date_trunc`` -> ``TimestampTrunc``,
``now()`` -> ``CurrentTimestamp``) and everything else to ``Anonymous``. Rather than guess its
internal names, the allowlists are built by parsing example calls with the same parser the
validator uses, so they stay correct across sqlglot versions.
"""

import sqlglot
from sqlglot import exp

# Explicitly dangerous (sleep/DoS, file and large-object access, remote connections, settings).
DENIED_FUNCTIONS = frozenset(
    {
        "pg_sleep",
        "pg_sleep_for",
        "pg_sleep_until",
        "pg_read_file",
        "pg_read_binary_file",
        "pg_ls_dir",
        "pg_stat_file",
        "lo_import",
        "lo_export",
        "lo_get",
        "dblink",
        "dblink_exec",
        "dblink_connect",
        "set_config",
        "current_setting",
        "pg_terminate_backend",
        "pg_cancel_backend",
        "query_to_xml",
    }
)
DENIED_PREFIXES = ("pg_", "dblink", "lo_")

_SAFE_CALLS = """
count(x), sum(x), avg(x), min(x), max(x), stddev(x), stddev_samp(x), stddev_pop(x),
variance(x), var_samp(x), var_pop(x), corr(x, y), bool_and(x), bool_or(x),
string_agg(x, ','), percentile_cont(0.5) WITHIN GROUP (ORDER BY x),
percentile_disc(0.5) WITHIN GROUP (ORDER BY x), mode() WITHIN GROUP (ORDER BY x),
row_number() OVER (), rank() OVER (), dense_rank() OVER (), percent_rank() OVER (),
cume_dist() OVER (), ntile(4) OVER (), lag(x) OVER (), lead(x) OVER (),
first_value(x) OVER (), last_value(x) OVER (),
date_trunc('month', x), date_part('year', x), extract(year FROM x), age(x, y),
make_date(2017, 1, 1), to_char(x, 'YYYY-MM'), to_date('2017', 'YYYY'), current_date, now(),
justify_days(x), lower(x), upper(x), initcap(x), length(x), char_length(x),
substring(x, 1, 2), substr(x, 1, 2), trim(x), ltrim(x), rtrim(x), replace(x, 'a', 'b'),
concat(x, y), concat_ws(',', x, y), left(x, 2), right(x, 2), position('a' IN x),
strpos(x, 'a'), split_part(x, ',', 1), lpad(x, 5), rpad(x, 5), reverse(x),
starts_with(x, 'a'), round(x), round(x, 2), ceil(x), ceiling(x), floor(x), abs(x), sqrt(x),
power(x, 2), exp(x), ln(x), log(x), mod(x, 2), sign(x), trunc(x), greatest(x, y),
least(x, y), width_bucket(x, 0, 10, 5), coalesce(x, y), nullif(x, y),
CASE WHEN x THEN 1 ELSE 0 END, CAST(x AS INT),
EXISTS (SELECT 1), x = ANY(ARRAY[1, 2]), x ~ 'a',
(x AND y) OR (NOT z), x = y, x <> y, x != y, x < y, x <= y, x > y, x >= y,
x + y, x - y, x * y, x / y, x % y, -x, x ^ 2, x || y, x LIKE 'a', x ILIKE 'a',
x NOT LIKE 'a', x SIMILAR TO 'a', x IN (1, 2), x NOT IN (1, 2), x BETWEEN 1 AND 2,
x IS NULL, x IS NOT NULL, x IS DISTINCT FROM y, x IS TRUE, x AT TIME ZONE 'UTC'
"""
# Predicates and operators sqlglot also models as functions are listed above too (EXISTS,
# ARRAY, the ~ regex match). ROW(...) is deliberately absent: generated queries never need it.

_SAFE_CASTS = """
x::int, x::integer, x::bigint, x::smallint, x::numeric, x::numeric(10, 2), x::real,
x::double precision, x::float, x::text, x::varchar, x::varchar(10), x::char, x::date,
x::timestamp, x::timestamptz, x::interval, x::boolean, x::time
"""


def function_name(node: exp.Func) -> str:
    """Lower-case function name as the validator compares it."""
    return (node.name if isinstance(node, exp.Anonymous) else node.sql_name()).lower()


def _names(calls: str) -> frozenset[str]:
    tree = sqlglot.parse_one(f"SELECT {calls}", read="postgres")
    return frozenset(function_name(f) for f in tree.find_all(exp.Func))


def _types(casts: str) -> frozenset[object]:
    tree = sqlglot.parse_one(f"SELECT {casts}", read="postgres")
    return frozenset(t.this for t in tree.find_all(exp.DataType))


ALLOWED_FUNCTIONS = _names(_SAFE_CALLS) - DENIED_FUNCTIONS
ALLOWED_CAST_TYPES = _types(_SAFE_CASTS)


def is_denied(name: str) -> bool:
    """Explicitly dangerous, by name or by prefix (pg_*, dblink*, lo_*)."""
    return name in DENIED_FUNCTIONS or name.startswith(DENIED_PREFIXES)
