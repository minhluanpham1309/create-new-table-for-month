import json
import logging
import pymysql
import hashlib
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Optional, Any, Set, Tuple
from urllib.parse import unquote

from common import (
    # constants
    JST, PATTERN_YYYY_MM_DD_HH, PATTERN_YYYYMM,
    CHUNK_INDEX_TRACKING_DATA_KEY, DELIMITER,
    ORGANIC_PAGES, SOCIAL_PAGES,
    CACHE_DOMAIN, CACHE_UTM_SOURCE, CACHE_UTM_MEDIUM,
    BATCH_SIZE, MAX_DEADLOCK_RETRY,
    # enums
    ReferrerDomainType, CacheType,
    # helpers
    get_max_workers,
    get_redis_client,
    get_package_redis_client,
    get_region,
    get_secret,
    get_db_connection,
    run_step,
    scan_redis_keys,
    get_redis_set_data,
    delete_redis_key,
    get_from_package_redis_cache,
    set_to_package_redis_cache,
)

# logger = logging.getLogger()
# logger.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

_thread_local = threading.local()

# ============================================================================
# LAMBDA HANDLER
# ============================================================================

def lambda_handler(event=None, context=None):
    """
    Triggered hourly by EventBridge.
    Moves analytics data from Redis to per-site MySQL schemas.
    """
    logger.info("=" * 60)
    logger.info("START  MOVE DATA TO MYSQL")
    logger.info("=" * 60)

    region = get_region()
    secret = run_step("get_secret", get_secret, region)
    run_step("init_redis", get_redis_client)

    # One connection for the coordinator (schema lookups etc.)
    cnx = run_step("open_db_connection", get_db_connection, secret)

    try:
        stats = run_step("execute_move_data", execute_move_data, cnx, secret)

        logger.info("=" * 60)
        logger.info("END  MOVE DATA TO MYSQL")
        logger.info("=" * 60)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Success", "stats": stats}),
        }

    except Exception:
        cnx.rollback()
        logger.exception("Fatal error in lambda_handler")
        raise

    finally:
        cnx.close()
        logger.info("Coordinator DB connection closed")


# ============================================================================
# MAIN LOGIC
# ============================================================================

def execute_move_data(coordinator_cnx: pymysql.connections.Connection, secret: Dict) -> Dict[str, Any]:
    """
    Determine target keys and table name based on mode, then move data to MySQL.

    mode="normal" (default — regular hourly run):
      - Scans Redis for keys matching 1 hour ago (YYYY-MM-DD HH pattern).
      - date_key  = 1 hour ago formatted as PATTERN_YYYY_MM_DD_HH
      - table_name = 1 hour ago formatted as PATTERN_YYYYMM
    """
    now_jst = datetime.now(JST)

    one_hour_ago_dt = now_jst - timedelta(hours=1)
    date_key        = one_hour_ago_dt.strftime(PATTERN_YYYY_MM_DD_HH)
    table_name      = one_hour_ago_dt.strftime(PATTERN_YYYYMM)

    logger.info(f"date_key  : {date_key}")
    logger.info(f"table_name: {table_name}")

    all_keys      = scan_redis_keys(f"*{date_key}*")
    filtered_keys = [k for k in all_keys if CHUNK_INDEX_TRACKING_DATA_KEY not in k]

    logger.info(f"Total keys found  : {len(all_keys)}")
    logger.info(f"Keys after filter : {len(filtered_keys)}")

    if not filtered_keys:
        return {"date_key": date_key, "table_name": table_name,
                "total_keys": 0, "successful": 0, "failed": 0}

    schema_set = get_schema_set(coordinator_cnx)
    logger.info(f"Active DB schemas : {len(schema_set)}")

    stats = process_keys_parallel(filtered_keys, schema_set, table_name, secret)

    return {
        "date_key":    date_key,
        "table_name":  table_name,
        "total_keys":  len(filtered_keys),
        "successful":  stats["successful"],
        "failed":      stats["failed"],
    }


# ============================================================================
# SCHEMA HELPERS
# ============================================================================

def get_schema_set(connection: pymysql.connections.Connection) -> Set[str]:
    """Return the set of all MySQL schema names."""
    with connection.cursor() as cur:
        cur.execute("SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA")
        rows = cur.fetchall()
    return {row["SCHEMA_NAME"] for row in rows}


# ============================================================================
# PARALLEL KEY PROCESSING
# ============================================================================

def _thread_init(secret: Dict, connections: list, lock: threading.Lock):
    """
    Runs exactly once when a worker thread starts.
    Opens a DB connection, stores it in thread-local storage, and registers
    it in the shared `connections` list so the coordinator can close it after
    the pool exits.
    """
    conn = get_db_connection(secret)
    _thread_local.conn = conn
    _thread_local.domain_cache  = {}  
    _thread_local.utm_src_cache = {}
    _thread_local.utm_med_cache = {}
    with lock:
        connections.append(conn)
    logger.info(f"Thread {threading.current_thread().name}: DB connection opened")


def process_keys_parallel(
    keys: List[str],
    schema_set: Set[str],
    table_name: str,
    secret: Dict,
) -> Dict[str, int]:
    """
    Each worker thread reuses a single DB connection (opened once in _thread_init)
    for all keys it handles.  Connections are closed after the pool is joined.
    """
    successful  = 0
    failed      = 0
    # FIX 3: track connections opened by threads so we can close them after the
    # pool exits — the old "cleanup_pool" approach was wrong because it created
    # brand-new threads (with brand-new connections) and closed those instead.
    connections : List[pymysql.connections.Connection] = []
    lock        = threading.Lock()

    with ThreadPoolExecutor(
        max_workers=get_max_workers(),
        initializer=_thread_init,
        initargs=(secret, connections, lock),
    ) as pool:
        future_map: Dict[Any, str] = {}

        for key in keys:
            # Key format: {site_id}_{YYYY-MM-DD HH}_{type_key}:{chunk_idx}
            parts = key.split("_")
            if len(parts) < 3:
                logger.warning(f"Skipping malformed key: {key}")
                continue

            site_id  = parts[0]
            type_key = parts[2].split(":")[0]

            if site_id not in schema_set:
                logger.info(f"Schema not found for site {site_id} — deleting key")
                delete_redis_key(key)
                continue

            # FIX 4: removed redundant secret + schema_set args from process_single_key
            future = pool.submit(process_single_key, key, site_id, type_key, table_name)
            future_map[future] = key

        for future in as_completed(future_map):
            key = future_map[future]
            try:
                ok = future.result()
                if ok:
                    successful += 1
                else:
                    failed += 1
            except Exception:
                logger.exception(f"Unhandled exception for key: {key}")
                failed += 1

    # Pool has joined — all threads finished; now close their connections
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass
    logger.info(f"Closed {len(connections)} thread DB connections")
    logger.info(f"Parallel processing done — success={successful}  failed={failed}")
    return {"successful": successful, "failed": failed}


# FIX 4 cont.: removed unused `secret` and `schema_set` params
def process_single_key(
    redis_key: str,
    site_id: str,
    type_key: str,
    table_name: str,
) -> bool:
    """Worker: reuses the thread-local DB connection opened in _thread_init."""
    try:
        connection = _thread_local.conn

        dispatch = {
            "v": process_pageview,
            "c": process_click,
            "s": process_scroll,
            "r": process_read,
        }
        handler = dispatch.get(type_key)
        if handler is None:
            logger.warning(f"Unknown type_key '{type_key}' for key {redis_key}")
            return False

        return handler(connection, redis_key, site_id, table_name)

    except Exception:
        logger.exception(f"Error in worker for key: {redis_key}")
        try:
            _thread_local.conn.rollback()
        except Exception:
            pass
        return False


# ============================================================================
# DOMAIN / UTM CACHING
# ============================================================================

def resolve_domain_type(domain: str) -> ReferrerDomainType:
    if not domain:
        return ReferrerDomainType.NONE
    for p in ORGANIC_PAGES:
        if p in domain:
            return ReferrerDomainType.ORGANIC
    for p in SOCIAL_PAGES:
        if p in domain:
            return ReferrerDomainType.SOCIAL
    return ReferrerDomainType.NONE


def _cache_key_for(cache_type: CacheType) -> str:
    mapping = {
        CacheType.DOMAIN:     CACHE_DOMAIN,
        CacheType.UTM_SOURCE: CACHE_UTM_SOURCE,
        CacheType.UTM_MEDIUM: CACHE_UTM_MEDIUM,
    }
    return mapping[cache_type]


def get_id_cached(
    connection: pymysql.connections.Connection,
    cache_type: CacheType,
    value: str,
) -> Optional[int]:
    """
    1. Check Redis hash cache.
    2. On miss: upsert into DB, then populate cache.
    """
    if not value:
        return None

    cache_key = _cache_key_for(cache_type)
    cached    = get_from_package_redis_cache(cache_key, value)
    if cached is not None:
        return cached

    db_id = _save_to_db(connection, cache_type, value)
    if db_id is not None:
        set_to_package_redis_cache(cache_key, value, db_id)
    return db_id


def _save_to_db(
    connection: pymysql.connections.Connection,
    cache_type: CacheType,
    value: str,
) -> Optional[int]:
    if   cache_type == CacheType.DOMAIN:     return _upsert_referrer_domain(connection, value)
    elif cache_type == CacheType.UTM_SOURCE: return _upsert_utm_source(connection, value)
    elif cache_type == CacheType.UTM_MEDIUM: return _upsert_utm_medium(connection, value)
    raise ValueError(f"Unknown CacheType: {cache_type}")


def _upsert_referrer_domain(connection, domain: str) -> Optional[int]:
    try:
        dtype = resolve_domain_type(domain)
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO HEAT_MAP.REFERRER_DOMAIN (DOMAIN, TYPE) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)",
                (domain, dtype.name),
            )
            row_id = cur.lastrowid
        connection.commit()
        return row_id
    except Exception:
        logger.exception(f"Upsert REFERRER_DOMAIN failed: {domain}")
        connection.rollback()
        return None


def _upsert_utm_source(connection, utm_source: str) -> Optional[int]:
    try:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO HEAT_MAP.REFERRER_UTM_SOURCE (UTM_SOURCE) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)",
                (utm_source,),
            )
            row_id = cur.lastrowid
        connection.commit()
        return row_id
    except Exception:
        logger.exception(f"Upsert REFERRER_UTM_SOURCE failed: {utm_source}")
        connection.rollback()
        return None


def _upsert_utm_medium(connection, utm_medium: str) -> Optional[int]:
    try:
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO HEAT_MAP.REFERRER_UTM_MEDIUM (UTM_MEDIUM) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)",
                (utm_medium,),
            )
            row_id = cur.lastrowid
        connection.commit()
        return row_id
    except Exception:
        logger.exception(f"Upsert REFERRER_UTM_MEDIUM failed: {utm_medium}")
        connection.rollback()
        return None


# ============================================================================
# PARAMETER PAIRS
# ============================================================================

def extract_parameter_pairs(parameters_str: str) -> List[Dict]:
    """
    Parse query-string parameters, exclude utm_* keys, and return a list of
    dicts with {id, key, value} — matching the original Java logic.
    """
    if not parameters_str:
        return []

    pairs = []
    for raw_pair in parameters_str.split("&"):
        if "=" not in raw_pair:
            continue
        k, _, v = raw_pair.partition("=")
        try:
            key = unquote(k, encoding="utf-8", errors="replace")
            val = unquote(v, encoding="utf-8", errors="replace")
        except Exception:
            key, val = k, v

        if key.startswith("utm_"):
            continue

        pair_id = hashlib.md5(f"{key}{val}".encode()).hexdigest()
        pairs.append({"id": pair_id, "key": key, "value": val})

    return pairs


def build_group_id(pairs: List[Dict]) -> str:
    sorted_pairs = sorted(pairs, key=lambda x: x["key"])
    joined = "".join(f"{p['key']}{p['value']}" for p in sorted_pairs)
    return hashlib.md5(joined.encode()).hexdigest()


def save_parameter_pairs(
    connection: pymysql.connections.Connection,
    parameter_pairs: List[Dict],
) -> bool:
    """
    Upsert into PARAMETER_PAIR and PARAMETER_PAIR_GROUP tables.
    Retries up to MAX_DEADLOCK_RETRY times on MySQL deadlock (error 1213).
    """
    if not parameter_pairs:
        return True

    group_id = build_group_id(parameter_pairs)

    for attempt in range(1, MAX_DEADLOCK_RETRY + 1):
        try:
            with connection.cursor() as cur:
                for pair in parameter_pairs:
                    cur.execute(
                        "INSERT INTO HEAT_MAP.PARAMETER_PAIR (ID, `KEY`, `VALUE`) VALUES (%s, %s, %s) "
                        "ON DUPLICATE KEY UPDATE `KEY` = `KEY`, `VALUE` = `VALUE`",
                        (pair["id"], pair["key"], pair["value"]),
                    )
                for pair in parameter_pairs:
                    cur.execute(
                        "INSERT INTO HEAT_MAP.PARAMETER_PAIR_GROUP (ID, PARAMETER_PAIR_ID) VALUES (%s, %s) "
                        "ON DUPLICATE KEY UPDATE ID = ID",
                        (group_id, pair["id"]),
                    )
            connection.commit()
            return True

        except pymysql.err.OperationalError as exc:
            if exc.args[0] == 1213:  # deadlock
                connection.rollback()
                logger.warning(f"Deadlock on parameter pairs (attempt {attempt}/{MAX_DEADLOCK_RETRY})")
                if attempt == MAX_DEADLOCK_RETRY:
                    logger.error("Deadlock retry limit reached for parameter pairs")
                    return False
            else:
                connection.rollback()
                logger.exception("OperationalError saving parameter pairs")
                return False

        except Exception:
            connection.rollback()
            logger.exception("Error saving parameter pairs")
            return False

    return False


# ============================================================================
# DATA PARSERS
# ============================================================================

def parse_pageview_data(
    raw_data: Set[str],
    connection: pymysql.connections.Connection,
    domain_cache:  Dict[str, Optional[int]],
    utm_src_cache: Dict[str, Optional[int]],
    utm_med_cache: Dict[str, Optional[int]],
) -> Tuple[List[Dict], List[Dict]]:
    """
    Format:
      dateCreate;-;referrerId;-;url;-;urlId;-;device;-;winWidth;-;ipA;-;userAgent
      ;-;parameters;-;domain;-;utmSource;-;utmMedium

    Returns (pageview_dtos, all_parameter_pairs)
    """
    parsed           = []
    all_pairs        = []

    for row in raw_data:
        try:
            p = row.strip('"').split(DELIMITER)
            if len(p) < 3:
                continue

            # Parameter pairs
            params_str = p[8] if len(p) > 8 else ""
            pairs      = extract_parameter_pairs(params_str)
            group_id   = build_group_id(pairs) if pairs else None
            all_pairs.extend(pairs)

            dto: Dict[str, Any] = {
                "dateCreate":         p[0]  if len(p) > 0  else None,
                "referrerId":         p[1]  if len(p) > 1  else None,
                "url":                p[2]  if len(p) > 2  else None,
                "urlId":              p[3]  if len(p) > 3  else None,
                "device":             p[4]  if len(p) > 4  else None,
                "winWidth":           p[5]  if len(p) > 5  else "0",
                "ipA":               (p[6]  if len(p) > 6 and p[6] and len(p[6]) < 50 else "0.0.0.0"),
                "userAgent":          p[7]  if len(p) > 7  else "na",
                "parameterPairGroupId": group_id,
                "refDomainId":        None,
                "refUtmSourceId":     None,
                "refUtmMediumId":     None,
            }

            if len(p) > 9 and p[9].strip():
                d = p[9]
                if d not in domain_cache:
                    domain_cache[d] = get_id_cached(connection, CacheType.DOMAIN, d)
                dto["refDomainId"] = domain_cache[d]

            if len(p) > 10 and p[10].strip():
                s = p[10]
                if s not in utm_src_cache:
                    utm_src_cache[s] = get_id_cached(connection, CacheType.UTM_SOURCE, s)
                dto["refUtmSourceId"] = utm_src_cache[s]

            if len(p) > 11 and p[11].strip():
                m = p[11]
                if m not in utm_med_cache:
                    utm_med_cache[m] = get_id_cached(connection, CacheType.UTM_MEDIUM, m)
                dto["refUtmMediumId"] = utm_med_cache[m]

            parsed.append(dto)

        except Exception:
            logger.exception(f"Error parsing pageview row: {row[:120]}")

    return parsed, all_pairs


def parse_click_data(raw_data: Set[str]) -> List[Dict]:
    parsed = []
    for row in raw_data:
        try:
            p = row.strip('"').split(DELIMITER)
            if len(p) < 11:
                continue
            parsed.append({
                "dateCreate": p[0], "device":    p[1], "winWidth": p[2],
                "docWidth":   p[3], "docHeight": p[4], "referrerId": p[5],
                "xpos":       p[6], "ypos":      p[7], "link":    p[8],
                "title":      p[9], "urlId":     p[10],
            })
        except Exception:
            logger.exception(f"Error parsing click row: {row[:120]}")
    return parsed


def parse_scroll_data(raw_data: Set[str]) -> List[Dict]:
    parsed = []
    for row in raw_data:
        try:
            p = row.strip('"').split(DELIMITER)
            if len(p) < 7:
                continue
            parsed.append({
                "dateCreate": p[0], "device":    p[1], "winWidth":  p[2],
                "docHeight":  p[3], "referrerId": p[4], "pos":       p[5],
                "urlId":      p[6],
            })
        except Exception:
            logger.exception(f"Error parsing scroll row: {row[:120]}")
    return parsed


def parse_read_data(raw_data: Set[str]) -> List[Dict]:
    parsed = []
    for row in raw_data:
        try:
            p = row.strip('"').split(DELIMITER)
            if len(p) < 8:
                continue
            parsed.append({
                "dateCreate": p[0], "device":    p[1], "winWidth":   p[2],
                "winHeight":  p[3], "docHeight": p[4], "referrerId": p[5],
                "pos":        p[6], "urlId":     p[7],
            })
        except Exception:
            logger.exception(f"Error parsing read row: {row[:120]}")
    return parsed


# ============================================================================
# PROCESS HANDLERS  (one per data type)
# ============================================================================

def _load_and_process(
    connection, redis_key: str, site_id: str, table_name: str,
    parse_fn, insert_fn,
    extra_parse_args: tuple = (),
) -> bool:
    """
    Generic load-parse-insert-delete pipeline shared by all four types.
    For pageview, parse_fn returns (list, pairs); for others it returns a list.
    """
    raw = get_redis_set_data(redis_key)
    if not raw:
        logger.debug(f"No data in Redis key {redis_key} — skipping and deleting")
        delete_redis_key(redis_key)
        return True

    result = parse_fn(raw, *extra_parse_args)
    pairs  = None
    parsed = result

    if isinstance(result, tuple):
        parsed, pairs = result

    if not parsed:
        delete_redis_key(redis_key)
        return True

    ok = insert_fn(connection, site_id, parsed, table_name)
    if not ok:
        return False

    # Pageview extras (store_total_pv + parameter_pairs) — non-fatal failures
    if pairs is not None:
        try:
            pv_ok = store_total_pv(connection, site_id, table_name, len(parsed))
            if not pv_ok:
                logger.warning(f"store_total_pv failed for site {site_id}")
        except Exception:
            logger.exception(f"store_total_pv exception for site {site_id}")

        if pairs:
            unique_pairs = list({p["id"]: p for p in pairs}.values())
            pair_ok = save_parameter_pairs(connection, unique_pairs)
            if not pair_ok:
                logger.warning(f"save_parameter_pairs failed for site {site_id}")
                return False

    # Always delete the key once the main insert succeeded
    delete_redis_key(redis_key)
    return True


def process_pageview(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    return _load_and_process(
        connection, redis_key, site_id, table_name,
        parse_fn=parse_pageview_data,
        insert_fn=insert_pageviews,
        extra_parse_args=(
            connection,
            _thread_local.domain_cache,
            _thread_local.utm_src_cache,
            _thread_local.utm_med_cache,
        ),
    )


def process_click(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    return _load_and_process(
        connection, redis_key, site_id, table_name,
        parse_fn=parse_click_data,
        insert_fn=insert_clicks,
    )


def process_scroll(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    return _load_and_process(
        connection, redis_key, site_id, table_name,
        parse_fn=parse_scroll_data,
        insert_fn=insert_scrolls,
    )


def process_read(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    return _load_and_process(
        connection, redis_key, site_id, table_name,
        parse_fn=parse_read_data,
        insert_fn=insert_reads,
    )


# ============================================================================
# DATABASE INSERT HELPERS
# ============================================================================

def _execute_batch(
    connection: pymysql.connections.Connection,
    sql: str,
    rows: List[tuple],
    label: str,
) -> bool:
    """
    Execute inserts in batches of BATCH_SIZE, committing after each batch.
    Rolls back and returns False on any error.
    """
    try:
        with connection.cursor() as cur:
            for i in range(0, len(rows), BATCH_SIZE):
                cur.executemany(sql, rows[i:i + BATCH_SIZE])
        connection.commit()
        logger.info(f"Inserted {len(rows)} {label} records")
        return True

    except Exception:
        connection.rollback()
        logger.exception(f"Batch insert failed for {label}")
        return False


def insert_pageviews(connection, site_id: str, data: List[Dict], table_name: str) -> bool:
    table = f"`{site_id}`.`{table_name}_referrer`"
    sql   = (
        f"INSERT INTO {table} "
        "(date_added, referrer_id, url, url_id, ref_domain_id, ref_utm_source_id, "
        "ref_utm_medium_id, parameter_pair_group_id, device, win_width, ipa, user_agent) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            item.get("dateCreate"),
            item.get("referrerId"),
            item.get("url"),
            item.get("urlId"),
            item.get("refDomainId"),
            item.get("refUtmSourceId"),
            item.get("refUtmMediumId"),
            item.get("parameterPairGroupId"),
            item.get("device"),
            item.get("winWidth"),
            item.get("ipA"),
            (item.get("userAgent") or "na")[:499],
        )
        for item in data
    ]
    return _execute_batch(connection, sql, rows, f"pageview/{site_id}")


def insert_clicks(connection, site_id: str, data: List[Dict], table_name: str) -> bool:
    table = f"`{site_id}`.`{table_name}_click`"
    sql   = (
        f"INSERT INTO {table} "
        "(date_added, xpos, ypos, win_width, doc_width, doc_height, device, referrer_id, url_id, link, title) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            item.get("dateCreate"),  item.get("xpos"),       item.get("ypos"),
            item.get("winWidth"),    item.get("docWidth"),   item.get("docHeight"),
            item.get("device"),      item.get("referrerId"), item.get("urlId"),
            item.get("link"),        item.get("title"),
        )
        for item in data
    ]
    return _execute_batch(connection, sql, rows, f"click/{site_id}")


def insert_scrolls(connection, site_id: str, data: List[Dict], table_name: str) -> bool:
    table = f"`{site_id}`.`{table_name}_scroll`"
    sql   = (
        f"INSERT INTO {table} "
        "(date_added, device, win_width, doc_height, referrer_id, pos, url_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            item.get("dateCreate"), item.get("device"),     item.get("winWidth"),
            item.get("docHeight"),  item.get("referrerId"), item.get("pos"),
            item.get("urlId"),
        )
        for item in data
    ]
    return _execute_batch(connection, sql, rows, f"scroll/{site_id}")


def insert_reads(connection, site_id: str, data: List[Dict], table_name: str) -> bool:
    table = f"`{site_id}`.`{table_name}_read`"
    sql   = (
        f"INSERT INTO {table} "
        "(date_added, device, win_width, win_height, doc_height, referrer_id, pos, url_id) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            item.get("dateCreate"), item.get("device"),     item.get("winWidth"),
            item.get("winHeight"),  item.get("docHeight"),  item.get("referrerId"),
            item.get("pos"),        item.get("urlId"),
        )
        for item in data
    ]
    return _execute_batch(connection, sql, rows, f"read/{site_id}")


# ============================================================================
# TOTAL PV TRACKING
# ============================================================================

def get_package_code_from_redis(site_id: str) -> Optional[str]:
    """
    Fetch PACKAGE_CODE from Redis hash 'list_sites_setup' using site_id as field.
    Mirrors Java: redissonUtils.getHashByKey("list_sites_setup", siteId)
    """
    try:
        val = get_package_redis_client().hget("list_sites_setup", site_id)
        return val if val else None
    except Exception:
        logger.exception(f"get_package_code_from_redis failed for site={site_id}")
        return None


def store_total_pv(
    connection: pymysql.connections.Connection,
    site_id: str,
    table_name: str,
    count: int,
) -> bool:
    """
    Upsert a row into HEAT_MAP.TRACKED_PV.
    table_name is in YYYYMM format; YEAR and MONTH are extracted from it.
    PACKAGE_CODE is resolved from Redis hash 'list_sites_setup'.
    """
    package_code = get_package_code_from_redis(site_id)
    if package_code is None:
        logger.info(f"store_total_pv: package code is null for site={site_id}, skipping")
        return False

    try:
        year  = int(table_name[:4])
        month = int(table_name[4:6])

        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO HEAT_MAP.TRACKED_PV (PACKAGE_CODE, SITE_ID, YEAR, MONTH, COUNT, CREATED, UPDATED) "
                "VALUES (%s, %s, %s, %s, %s, NOW(), NOW()) "
                "ON DUPLICATE KEY UPDATE COUNT = COUNT + VALUES(COUNT), UPDATED = NOW()",
                (package_code, site_id, year, month, count),
            )
        connection.commit()
        logger.info(f"Stored total PV {count} for site={site_id} table={table_name}")
        return True
    except Exception:
        connection.rollback()
        logger.exception(f"store_total_pv failed for site={site_id}")
        return False


# ============================================================================
# LOCAL ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    lambda_handler()
