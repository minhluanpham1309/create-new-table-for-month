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
    get_data_redis_wrapper,
    get_package_redis_wrapper,
    get_region,
    get_secret,
    get_db_connection,
    run_step,
    scan_redis_keys,
    get_redis_set_data,
    delete_redis_key,
    get_from_setting_cache,
    set_to_setting_cache,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_thread_local = threading.local()

# ============================================================================
# LAMBDA HANDLERS
# ============================================================================

def move_handler(event=None, context=None):
    """
    Triggered hourly by EventBridge.
    Moves analytics data from Redis to per-site MySQL schemas.
    """
    logger.info("=" * 60)
    logger.info("START MOVE DATA TO MYSQL")
    logger.info("=" * 60)
    
    logger.info("Connecting resources...")
    region = get_region()
    secret = run_step("get_secret", get_secret, region)
    run_step("init_redis", get_data_redis_wrapper)

    # One connection for the coordinator (schema lookups etc.)
    cnx = run_step("open_db_connection", get_db_connection, secret)
    logger.info("Resources connected")

    try:
        stats = run_step("execute_move_data", execute_move_data, cnx, secret)

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Success", "stats": stats}),
        }

    except Exception:
        cnx.rollback()
        logger.error("Fatal error in move_handler")
        raise

    finally:
        cnx.close()
        logger.info("Coordinator DB connection closed")

        logger.info("=" * 60)
        logger.info("END MOVE DATA TO MYSQL")
        logger.info("=" * 60)


def move_missing_handler(event=None, context=None):
    """
    Triggered on schedule to backfill/move missing analytics data.
    Mimics Java ExecuteMoveMissingDataToMySQLV2.execute logic:
      - Consider keys for the month of (now - 2 hours)
      - Exclude keys from current hour and the previous hour
      - Filter out chunk/index keys
      - Move remaining keys' data to MySQL
    """
    logger.info("=" * 60)
    logger.info("START MOVE MISSING DATA TO MYSQL")
    logger.info("=" * 60)

    logger.info("Connecting resources...")
    region = get_region()
    secret = run_step("get_secret", get_secret, region)
    run_step("init_redis", get_data_redis_wrapper)

    cnx = run_step("open_db_connection", get_db_connection, secret)
    logger.info("Resources connected")

    try:
        stats = run_step("execute_move_missing_data", execute_move_missing_data, cnx, secret)
        cnx.commit()

        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Success", "stats": stats}),
        }

    except Exception:
        cnx.rollback()
        logger.error("Fatal error in move_missing_handler")
        raise

    finally:
        cnx.close()
        logger.info("Coordinator DB connection closed")

        logger.info("=" * 60)
        logger.info("END MOVE MISSING DATA TO MYSQL")
        logger.info("=" * 60)


# ============================================================================
# MAIN LOGIC
# ============================================================================

def execute_move_data(coordinator_cnx: pymysql.connections.Connection, secret: Dict) -> Dict[str, Any]:
    """
    1. Determine target date key and table name (1 hour ago in JST).
    2. Scan Redis for matching keys.
    3. Load the active schema list.
    4. Dispatch per-key work to a thread pool (each thread opens its own DB connection).
    """
    
    now_jst      = datetime.now(JST)
    one_hour_ago = now_jst - timedelta(hours=1)
    date_key     = one_hour_ago.strftime(PATTERN_YYYY_MM_DD_HH)
    table_name   = one_hour_ago.strftime(PATTERN_YYYYMM)

    # Compact scan summary for traceability without noise
    logger.info(
        f"SCAN summary — date_key={date_key} table={table_name}"
    )

    all_keys      = scan_redis_keys(f"*{date_key}*")
    filtered_keys = [k for k in all_keys if CHUNK_INDEX_TRACKING_DATA_KEY not in k]
    chunk_count   = len(all_keys) - len(filtered_keys)

    logger.info(
        f"Keys — total={len(all_keys)} filtered={len(filtered_keys)} chunks={chunk_count}"
    )

    if not filtered_keys:
        return {"date_key": date_key, "table_name": table_name,
                "total_keys": 0, "successful": 0, "failed": 0}

    schema_set = get_schema_set(coordinator_cnx)
    logger.info(f"Active schemas: {len(schema_set)}")

    logger.info(f"Starting parallel processing — keys={len(filtered_keys)} workers={get_max_workers()}")
    stats = process_keys_parallel(filtered_keys, schema_set, table_name, secret)

    return {
        "date_key":    date_key,
        "table_name":  table_name,
        "total_keys":  len(filtered_keys),
        "successful":  stats["successful"],
        "failed":      stats["failed"],
    }


def execute_move_missing_data(coordinator_cnx: pymysql.connections.Connection, secret: Dict) -> Dict[str, Any]:
    """
    Backfill/move missing data similar to Java ExecuteMoveMissingDataToMySQLV2.execute.
    - Use month pattern for (now - 2 hours) to scan keys for that month
    - Exclude keys that belong to current hour and the previous hour
    - Filter out chunk/index keys
    - Process remaining keys in parallel
    """
    now_jst = datetime.now(JST)

    # Patterns
    current_hour_key   = now_jst.strftime(PATTERN_YYYY_MM_DD_HH)
    one_hour_before    = now_jst - timedelta(hours=1)
    one_hour_key       = one_hour_before.strftime(PATTERN_YYYY_MM_DD_HH)
    two_hours_before   = now_jst - timedelta(hours=2)
    month_pattern      = two_hours_before.strftime("%Y-%m")
    table_name         = two_hours_before.strftime(PATTERN_YYYYMM)

    # Scan Redis keys
    scan_start = datetime.now(JST)
    exclude_current = set(scan_redis_keys(f"*{current_hour_key}*"))
    exclude_one     = set(scan_redis_keys(f"*{one_hour_key}*"))
    all_month_keys  = set(scan_redis_keys(f"*{month_pattern}*"))

    # Remove non-missing keys
    candidate_keys = list(all_month_keys - exclude_current - exclude_one)

    # Filter out chunk/index keys
    filtered_keys = [k for k in candidate_keys if CHUNK_INDEX_TRACKING_DATA_KEY not in k]
    chunk_count   = len(candidate_keys) - len(filtered_keys)
    scan_elapsed = (datetime.now(JST) - scan_start).total_seconds()

    logger.info(
        f"SCAN summary — month=*{month_pattern}* table={table_name} total={len(all_month_keys)} "
        f"exclude_current={len(exclude_current)} exclude_prev={len(exclude_one)} filtered={len(filtered_keys)} "
        f"chunks={chunk_count} — scan_elapsed={scan_elapsed:.2f}s"
    )

    if not filtered_keys:
        return {
            "date_key": f"*{month_pattern}*",
            "table_name": table_name,
            "total_keys": 0,
            "successful": 0,
            "failed": 0,
        }

    schema_set = get_schema_set(coordinator_cnx)
    logger.info(f"Active schemas: {len(schema_set)}")

    logger.info(f"Starting parallel processing — keys={len(filtered_keys)} workers={get_max_workers()}")
    stats = process_keys_parallel(filtered_keys, schema_set, table_name, secret)

    return {
        "date_key":    f"*{month_pattern}*",
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
    successful = 0
    failed     = 0
    
    # Track connections opened by threads so we can close them after the
    # pool exits — the old "cleanup_pool" approach was wrong because it created
    # brand-new threads (with brand-new connections) and closed those instead.
    connections: List[pymysql.connections.Connection] = []
    lock = threading.Lock()
    
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
            
            site_id = parts[0]
            type_key = parts[2].split(":")[0]
            
            if site_id not in schema_set:
                logger.info(f"Schema not found for site {site_id} — deleting key")
                delete_redis_key(key)
                continue
            
            future = pool.submit(process_single_key, key, site_id, type_key, table_name)
            future_map[future] = key
        
        progress_interval = 25
        total = len(future_map)
        processed = 0

        for future in as_completed(future_map):
            key = future_map[future]
            processed += 1
            try:
                ok = future.result()
                if ok:
                    successful += 1
                else:
                    failed += 1
            except Exception:
                logger.error(f"Unhandled exception for key: {key}")
                failed += 1

            if processed == total or processed % progress_interval == 0:
                logger.info(
                    f"Parallel progress — processed={processed}/{total} success={successful} failed={failed}"
                )

    # Pool has joined — all threads finished; now close their connections
    for conn in connections:
        try:
            conn.close()
        except Exception:
            pass
    logger.info(
        f"Parallel processing done — success={successful} failed={failed}; closed_connections={len(connections)}"
    )
    return {"successful": successful, "failed": failed}


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
        logger.error(f"Error in worker for key: {redis_key}")
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
    cached    = get_from_setting_cache(cache_key, value)
    if cached is not None:
        return cached

    db_id = _save_to_db(connection, cache_type, value)
    if db_id is not None:
        set_to_setting_cache(cache_key, value, db_id)
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
        logger.error(f"Upsert REFERRER_DOMAIN failed: {domain}")
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
        logger.error(f"Upsert REFERRER_UTM_SOURCE failed: {utm_source}")
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
        logger.error(f"Upsert REFERRER_UTM_MEDIUM failed: {utm_medium}")
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

        if not key.startswith("utm_"):
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
    group_pairs_map: Dict[str, List[Dict]],
) -> bool:
    """
    Upsert into PARAMETER_PAIR and PARAMETER_PAIR_GROUP tables.
    Retries up to MAX_DEADLOCK_RETRY times on MySQL deadlock (error 1213).
    """
    if not group_pairs_map:
        return True

    pair_groups = [
        {
            "group_id": group_id,
            "id": pair["id"],
            "key": pair["key"],
            "value": pair["value"],
        }
        for group_id, pairs in group_pairs_map.items()
        for pair in pairs
    ]

    for i in range(0, len(pair_groups), BATCH_SIZE):
        if not _store_parameter_pairs_with_retry(connection, pair_groups[i:i + BATCH_SIZE]):
            return False

    return True


def _store_parameter_pairs_with_retry(
    connection: pymysql.connections.Connection,
    target_list: List[Dict],
) -> bool:
    retry_count = 0
    group_rows, pair_rows = _prepare_parameter_pair_rows(target_list)

    while True:
        try:
            _store_parameter_pairs_chunk(connection, group_rows, pair_rows)
            connection.commit()
            return True

        except pymysql.err.OperationalError as exc:
            if exc.args[0] != 1213:
                connection.rollback()
                logger.error("OperationalError saving parameter pairs")
                return False

            retry_count += 1
            connection.rollback()
            logger.warning(f"Deadlock on parameter pairs (attempt {retry_count}/{MAX_DEADLOCK_RETRY})")
            if retry_count >= MAX_DEADLOCK_RETRY:
                logger.error("Deadlock retry limit reached for parameter pairs")
                return False
            continue

        except Exception:
            connection.rollback()
            logger.error("Error saving parameter pairs")
            return False


def _build_parameter_pair_group_rows(target_list: List[Dict]) -> List[tuple]:
    return list(
        dict.fromkeys((pair["group_id"], pair["id"]) for pair in target_list)
    )


def _build_parameter_pair_rows(target_list: List[Dict]) -> List[tuple]:
    return list(
        dict.fromkeys((pair["id"], pair["key"], pair["value"]) for pair in target_list)
    )


def _prepare_parameter_pair_rows(target_list: List[Dict]) -> Tuple[List[tuple], List[tuple]]:
    return (
        _build_parameter_pair_group_rows(target_list),
        _build_parameter_pair_rows(target_list),
    )


def _store_parameter_pairs_chunk(
    connection: pymysql.connections.Connection,
    group_rows: List[tuple],
    pair_rows: List[tuple],
) -> None:
    group_sql = (
        "INSERT INTO HEAT_MAP.PARAMETER_PAIR_GROUP (ID, PARAMETER_PAIR_ID) VALUES (%s, %s) "
        "ON DUPLICATE KEY UPDATE ID = ID"
    )
    pair_sql = (
        "INSERT INTO HEAT_MAP.PARAMETER_PAIR (ID, `KEY`, `VALUE`) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE `KEY` = `KEY`, `VALUE` = `VALUE`"
    )

    with connection.cursor() as cur:
        cur.executemany(group_sql, group_rows)
        cur.executemany(pair_sql, pair_rows)


# ============================================================================
# DATA PARSERS
# ============================================================================

def parse_pageview_data(
    raw_data: Set[str],
    connection: pymysql.connections.Connection,
    domain_cache:  Dict[str, Optional[int]],
    utm_src_cache: Dict[str, Optional[int]],
    utm_med_cache: Dict[str, Optional[int]],
) -> Tuple[List[Dict], Dict[str, List[Dict]]]:
    parsed          = []
    group_pairs_map: Dict[str, List[Dict]] = {}   # group_id → pairs

    for row in raw_data:
        try:
            p = row.strip('"').split(DELIMITER)
            if len(p) < 3:
                continue

            pairs    = extract_parameter_pairs(p[8] if len(p) > 8 else "")
            group_id = build_group_id(pairs) if pairs else None

            if group_id and group_id not in group_pairs_map:
                group_pairs_map[group_id] = pairs

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
            logger.error(f"Error parsing pageview row: {row[:120]}")

    return parsed, group_pairs_map


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
            logger.error(f"Error parsing click row: {row[:120]}")
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
            logger.error(f"Error parsing scroll row: {row[:120]}")
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
            logger.error(f"Error parsing read row: {row[:120]}")
    return parsed


# ============================================================================
# PROCESS HANDLERS  (one per data type)
# ============================================================================
def process_pageview(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    extra_parse_args: tuple = (
        connection,
        _thread_local.domain_cache,
        _thread_local.utm_src_cache,
        _thread_local.utm_med_cache,
    )

    raw = get_redis_set_data(redis_key)
    if not raw:
        logger.info(f"[pv/referrer - SKIP] Redis key has no data, skip pageview processing: {redis_key}")
        return True

    logger.info(
        f"[pv/referrer - START] insert total datas={len(raw)} from key={redis_key} into site={site_id}"
    )
    parsed_data, group_pairs_map = parse_pageview_data(raw, *extra_parse_args)

    if not parsed_data:
        logger.error(f"[pv/referrer - ERROR] no parsed rows for key={redis_key}")
        return True

    ok = insert_pageviews(connection, site_id, parsed_data, table_name)
    if not ok:
        logger.error(f"[pv/referrer - ERROR] insert key={redis_key} failed for site={site_id} ")
        return False

    pv_ok = False
    try:
        pv_ok = store_total_pv(connection, site_id, table_name, len(parsed_data))
        if not pv_ok:
            logger.error(f"[pv/referrer - ERROR] store_total_pv failed of key={redis_key} for site {site_id}")
    except Exception:
        logger.error(f"[pv/referrer - ERROR] store_total_pv exception of key={redis_key} for site {site_id}")

    pair_ok = save_parameter_pairs(connection, group_pairs_map)
    if not pair_ok:
        logger.error(f"[pv/referrer - ERROR] parameter pair save failed site={site_id} key={redis_key}")
        ok = False

    if pv_ok:
        delete_redis_key(redis_key)
        logger.info(
            f"[pv/referrer - SUCCESS] insert total datas={len(parsed_data)} from key={redis_key} into site={site_id}"
        )
    return ok


def process_click(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    raw = get_redis_set_data(redis_key)
    if not raw:
        logger.info(f"[click - SKIP] Redis key has no data, skip click processing: {redis_key}")
        return True

    result = parse_click_data(raw)
    logger.info(
        f"[click - START] insert total datas={len(result)} from key={redis_key} into site={site_id}"
    )

    if not result:
        logger.error(f"[click - ERROR] no parsed rows for key={redis_key}")
        return True
    ok = insert_clicks(connection, site_id, result, table_name)
    if not ok:
        logger.error(f"[click - ERROR] insert key={redis_key} failed for site={site_id}")
        return False
    else:
        delete_redis_key(redis_key)
        logger.info(
            f"[click - SUCCESS] insert total datas={len(result)} from key={redis_key} into site={site_id}"
        )
    return ok


def process_scroll(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    raw = get_redis_set_data(redis_key)
    if not raw:
        logger.info(f"[scroll - SKIP] Redis key has no data, skip scroll processing: {redis_key}")
        return True

    result = parse_scroll_data(raw)
    logger.info(
        f"[scroll - START] insert total datas={len(result)} from key={redis_key} into site={site_id}"
    )

    if not result:
        logger.error(f"[scroll - ERROR] no parsed rows for key={redis_key}")
        return True
    ok = insert_scrolls(connection, site_id, result, table_name)
    if not ok:
        logger.error(f"[scroll - ERROR] insert key={redis_key} failed for site={site_id}")
        return False
    else:
        delete_redis_key(redis_key)
        logger.info(
            f"[scroll - SUCCESS] insert total datas={len(result)} from key={redis_key} into site={site_id}"
        )
    return ok


def process_read(connection, redis_key: str, site_id: str, table_name: str) -> bool:
    raw = get_redis_set_data(redis_key)
    if not raw:
        logger.info(f"[read - SKIP] Redis key has no data, skip read processing: {redis_key}")
        return True

    result = parse_read_data(raw)
    logger.info(
        f"[read - START] insert total datas={len(result)} from key={redis_key} into site={site_id}"
    )

    if not result:
        logger.error(f"[read - ERROR] no parsed rows for key={redis_key}")
        return True
    ok = insert_reads(connection, site_id, result, table_name)
    if not ok:
        logger.error(f"[read - ERROR] insert key={redis_key} failed for site={site_id}")
        return False
    else:
        delete_redis_key(redis_key)
        logger.info(
            f"[read - SUCCESS] insert total datas={len(result)} from key={redis_key} into site={site_id}"
        )
    return ok

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
        logger.error(f"Batch insert failed for {label}")
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
        "(date_added, xpos, ypos, win_width, doc_width, doc_height, "
        "device, referrer_id, url_id, link, title) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    rows = [
        (
            item.get("dateCreate"), item.get("xpos"),       item.get("ypos"),
            item.get("winWidth"),   item.get("docWidth"),   item.get("docHeight"),
            item.get("device"),     item.get("referrerId"), item.get("urlId"),
            item.get("link"),       item.get("title"),
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
    Mirrors Java: redissonUtils.getHashByKey("list_sites_setup", Integer.toString(siteId))

    Redisson (Java) serializes both field and value as JSON strings, so the
    actual Redis field is "\"931739482\"" and value is "\"456A445271B2...\"".
    Python's hget receives the raw string, so we must:
      - wrap site_id in JSON quotes when looking up the field
      - strip surrounding JSON quotes from the returned value
    """
    try:
        val = get_package_redis_wrapper().hget_str("list_sites_setup", site_id)
        if not val:
            return None
        return val
    except Exception:
        logger.error(f"get_package_code_from_redis failed for site={site_id}")
        return None


def get_package_code_from_db(
    connection: pymysql.connections.Connection,
    site_id: str,
) -> Optional[str]:
    """
    Fetch PACKAGE_CODE from HEAT_MAP.HEATMAP_SITE by site_id.
    Returns None when the site does not exist or PACKAGE_CODE is empty.
    """
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT PACKAGE_CODE FROM HEAT_MAP.HEATMAP_SITE WHERE SITE_ID = %s",
                (site_id,),
            )
            row = cur.fetchone()

        if not row:
            return None

        return row.get("PACKAGE_CODE") or None
    except Exception:
        logger.error(
            "Failed to resolve PACKAGE_CODE from DB fallback HEAT_MAP.HEATMAP_SITE for site_id=%s",
            site_id,
        )
        return None


def get_package_code(
    connection: pymysql.connections.Connection,
    site_id: str,
) -> Optional[str]:
    """
    Resolve PACKAGE_CODE by site_id from Redis first, then database.
    """
    package_code = get_package_code_from_redis(site_id)
    if package_code:
        return package_code

    return get_package_code_from_db(connection, site_id)


def store_total_pv(
    connection: pymysql.connections.Connection,
    site_id: str,
    table_name: str,
    count: int,
) -> bool:
    """
    Upsert a row into HEAT_MAP.TRACKED_PV.
    table_name is in YYYYMM format; YEAR and MONTH are extracted from it.
    PACKAGE_CODE is resolved from Redis first, then database fallback.
    """
    package_code = get_package_code(connection, site_id)
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
        logger.error(f"store_total_pv failed for site={site_id}")
        return False


# ============================================================================
# LOCAL ENTRY POINT
# ============================================================================
def lambda_handler(event=None, context=None):
    """
    Entry point for Lambda. Routes to specific handlers based on event['source'].

    - If source == "move.event" -> call move_handler
    - If source == "move.missing.event" -> call move_missing_handler
    - Else: log exception and do nothing (return 200 with no-op message)
    """
    try:
        # Safely extract action from event; let unexpected errors bubble up.
        action = event.get("action") if isinstance(event, dict) else None
    except Exception:
        logger.error("lambda_handler failed while parsing event")
        # Re-raise so Lambda treats this as a failure (enabling retries/alerts)
        raise
    if action == "move":
        return move_handler(event, context)
    elif action == "move_missing":
        return move_missing_handler(event, context)
    else:
        print(f"Unknown or missing action: {action}")
        return {"status": "ignored"}

if __name__ == "__main__":
    lambda_handler()
