import json
import logging
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

import boto3
import pymysql
import pytz
from dotenv import load_dotenv

from redis_utils import RedisWrapper as RedisUtils

# -----------------------------
# Bootstrap / Logging
# -----------------------------

# Load environment variables from .env file only when running locally.
if not os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
    load_dotenv()

logger = logging.getLogger()
logger.setLevel(logging.INFO)

jst = pytz.timezone("Asia/Tokyo")

# -----------------------------
# Constants (Redis keys, defaults)
# -----------------------------

REDIS_HASH_SITES_SETUP = "list_sites_setup"
REDIS_HASH_IP_BLOCK = "list_ip_block"
REDIS_HASH_PACKAGES_QUOTA = "list_packages_quota"
REDIS_HASH_PACKAGES_LIMIT = "list_packages_limit"

DEFAULT_LIMIT_REQUEST = 10000
DEFAULT_TIME_DELETE_DATA = 30
DEFAULT_PROFILE_ID = ""

DEFAULT_REGION = "ap-northeast-1"
DEFAULT_SECRET_NAME = "rds/db-test-private"


# -----------------------------
# DTOs
# -----------------------------


@dataclass(frozen=True)
class HMSiteDTO:
    site_id: str
    package_code: str
    ip_block: str
    is_delete: bool


@dataclass(frozen=True)
class PackageLimitDTO:
    package_code: str
    limit_request: int
    time_delete_data: int
    profile_id: str


@dataclass(frozen=True)
class HeatMapUrlConfigurationDTO:
    url_id: int
    url: str
    expression: str
    param_config: str
    sort_item: str

    @staticmethod
    def from_row(url_id: Any, url: Any, expression: Any, param_config: Any) -> "HeatMapUrlConfigurationDTO":
        url_str = (url or "").strip()
        sort_item = re.sub(r"^(http[s]?://(www[2]?\.)?)", "", url_str)
        return HeatMapUrlConfigurationDTO(
            url_id=int(url_id),
            url=url_str,
            expression=(expression or "-"),
            param_config=(param_config or "-"),
            sort_item=sort_item,
        )

    def to_redis_member(self) -> str:
        # Keep exact format to preserve compatibility with downstream readers
        return f"{self.url_id};_;{self.url};_;{self.expression};_;{self.param_config}"


# -----------------------------
# DAO
# -----------------------------


class HeatMapDAO:
    def __init__(self, db_conn: pymysql.connections.Connection):
        self.db = db_conn

    def get_list_heat_map_site_modify(self, hour: str) -> List[HMSiteDTO]:
        sql = """
              SELECT HMM.SITE_ID,
                     HMS.PACKAGE_CODE,
                     HMS.IP_BLOCK,
                     HMM.IS_DELETE
              FROM (SELECT M.*
                    FROM HEAT_MAP.HEATMAP_SITE_MODIFY M
                             JOIN (SELECT SITE_ID, MAX(CREATED) AS max_created
                                   FROM HEAT_MAP.HEATMAP_SITE_MODIFY
                                   WHERE DATE_FORMAT(CREATED, '%%H') = %s
                                     AND DATE (CREATED) = DATE(NOW())
                    GROUP BY SITE_ID) T ON M.SITE_ID = T.SITE_ID
              AND M.CREATED = T.max_created
              ) AS HMM
              LEFT JOIN HEAT_MAP.HEATMAP_SITE AS HMS
              ON HMM.SITE_ID = HMS.SITE_ID; \
              """
        with self.db.cursor() as cur:
            cur.execute(sql, (hour,))
            rows = cur.fetchall()

        out: List[HMSiteDTO] = []
        for r in rows:
            # DictCursor expected; fallback tuple support kept
            site_id = r["SITE_ID"] if isinstance(r, dict) else r[0]
            package_code = r["PACKAGE_CODE"] if isinstance(r, dict) else r[1]
            ip_block = r["IP_BLOCK"] if isinstance(r, dict) else r[2]
            is_delete = r["IS_DELETE"] if isinstance(r, dict) else r[3]
            out.append(
                HMSiteDTO(
                    site_id=str(site_id),
                    package_code=str(package_code or ""),
                    ip_block=str(ip_block or ""),
                    is_delete=bool(is_delete),
                )
            )
        return out

    def get_list_package_limit(self) -> List[PackageLimitDTO]:
        sql = """
              SELECT HS.PACKAGE_CODE,
                     IF(LQ.LIMIT_REQUEST IS NULL, %s, LQ.LIMIT_REQUEST)       AS LIMIT_REQUEST,
                     IF(LQ.TIME_DELETE_DATA IS NULL, %s, LQ.TIME_DELETE_DATA) AS TIME_DELETE_DATA,
                     IF(LQ.PROFILE_ID IS NULL, %s, LQ.PROFILE_ID)             AS PROFILE_ID
              FROM HEATMAP_SITE AS HS
                       LEFT JOIN A_LIMIT_QUANTITY AS LQ
                                 ON HS.PACKAGE_CODE = LQ.PACKAGE_CODE
              WHERE HS.IS_DELETED = 0
              GROUP BY HS.PACKAGE_CODE \
              """
        with self.db.cursor() as cur:
            cur.execute(sql, (DEFAULT_LIMIT_REQUEST, DEFAULT_TIME_DELETE_DATA, DEFAULT_PROFILE_ID))
            rows = cur.fetchall()

        out: List[PackageLimitDTO] = []
        for r in rows:
            out.append(
                PackageLimitDTO(
                    package_code=str(r["PACKAGE_CODE"] if isinstance(r, dict) else r[0] or ""),
                    limit_request=int(r["LIMIT_REQUEST"] if isinstance(r, dict) else r[1] or 0),
                    time_delete_data=int(r["TIME_DELETE_DATA"] if isinstance(r, dict) else r[2] or 0),
                    profile_id=str(r["PROFILE_ID"] if isinstance(r, dict) else r[3] or ""),
                )
            )
        return out

    def get_list_heat_map_site_update(self) -> List[str]:
        sql = """
              SELECT DOMAIN_ID
              FROM HEATMAP_SITE_DETAIL
              WHERE DATE (LAST_MODIFIED) = DATE (NOW())
                AND HOUR (LAST_MODIFIED) = HOUR (NOW())
                AND IS_DELETED = 0
              GROUP BY DOMAIN_ID \
              """
        with self.db.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return [str(r["DOMAIN_ID"] if isinstance(r, dict) else r[0]) for r in rows]

    def get_list_heat_map_url_configuration_by_domain_id(self, domain_id: str) -> List[HeatMapUrlConfigurationDTO]:
        sql = """
              SELECT URL_ID, URL, EXPRESSION, PARAM_CONFIG
              FROM HEATMAP_SITE_DETAIL
              WHERE DOMAIN_ID = %s
                AND LOCKED = 0
                AND IS_DELETED = 0
              ORDER BY URL DESC \
              """
        with self.db.cursor() as cur:
            cur.execute(sql, (domain_id,))
            rows = cur.fetchall()

        out: List[HeatMapUrlConfigurationDTO] = []
        for r in rows:
            url_id = r["URL_ID"] if isinstance(r, dict) else r[0]
            url = r["URL"] if isinstance(r, dict) else r[1]
            expression = r["EXPRESSION"] if isinstance(r, dict) else r[2]
            param_config = r["PARAM_CONFIG"] if isinstance(r, dict) else r[3]
            out.append(HeatMapUrlConfigurationDTO.from_row(url_id, url, expression, param_config))
        return out


# -----------------------------
# Infrastructure (Secrets / DB / Redis / SSL)
# -----------------------------


def get_region() -> str:
    return os.environ.get("AWS_REGION", DEFAULT_REGION)


def get_ssl_context(region: str = "ap-northeast-1") -> ssl.SSLContext:
    """Create SSL context with TLS 1.2+ (download CA bundle from AWS)"""
    try:
        ca_file_path = os.path.join(os.path.dirname(__file__), "certs", f"{region}-bundle.pem")

        # Fallback to global bundle if region-specific not found
        if not os.path.exists(ca_file_path):
            ca_file_path = os.path.join(os.path.dirname(__file__), "certs", "global-bundle.pem")

        if not os.path.exists(ca_file_path):
            raise FileNotFoundError(f"CA bundle not found at {ca_file_path}")

        logger.info(f"Loading CA bundle from: {ca_file_path}")

        # Create SSL context with TLS 1.2+
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.load_verify_locations(cafile=ca_file_path)

        # Configure verification
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        logger.info("SSL: VERIFY_CA")

        # Set minimum TLS 1.2
        ssl_context.minimum_version = ssl.TLSVersion.TLSv1_2

        return ssl_context

    except Exception as e:
        logger.error(f"Failed to create SSL context: {str(e)}")
        raise


def get_secret(region: str) -> Dict[str, Any]:
    secret_name = os.environ.get("RDS_SECRET_NAME", "rds/heatmap-db-secret")

    config = boto3.session.Config(
        connect_timeout=5,
        read_timeout=10,
        retries={"max_attempts": 3},
    )

    logger.info("Creating boto3 client for Secrets Manager...")
    client = boto3.client("secretsmanager", region_name=region, config=config)

    logger.info("Fetching secret value from Secrets Manager...")
    try:
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception:
        logger.error(f"Failed to fetch secret {secret_name}", exc_info=True)
        raise


def get_db_connection(secret: Dict[str, Any]) -> pymysql.connections.Connection:
    try:
        ssl_context = get_ssl_context()

        db_config = {
            "host": secret.get("host", os.getenv("DB_HOST")),
            "port": int(secret.get("port", os.getenv("DB_PORT", 3306))),
            "user": secret.get("username", os.getenv("DB_USER")),
            "password": secret.get("password", os.getenv("DB_PASSWORD")),
            "database": secret.get("dbname", os.getenv("DB_NAME", "HEAT_MAP")),
            "charset": "utf8mb4",
            "connect_timeout": 10,
            "cursorclass": pymysql.cursors.DictCursor,
            "ssl": ssl_context,
        }

        logger.info("Connecting to database...")
        connection = pymysql.connect(**db_config)
        logger.info("Database connection established")
        return connection

    except pymysql.err.OperationalError as e:
        error_code = e.args[0] if e.args else None
        if error_code == 2003:
            logger.error("Cannot connect to database server")
        elif error_code == 1045:
            logger.error("Access denied - check username/password")
        else:
            logger.error(f"Database connection error: {str(e)}")
        raise

    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise


# -----------------------------
# Steps (business logic)
# -----------------------------


def auto_update_site_setup(dao: HeatMapDAO, rds: RedisUtils) -> None:
    hour = (datetime.now(jst) - timedelta(hours=1)).strftime("%H")
    sites = dao.get_list_heat_map_site_modify(hour)
    logger.info("(Update site) sites_to_process=%d hour=%s", len(sites), hour)

    for s in sites:
        site_id = s.site_id
        if s.is_delete:
            logger.info("Deleting site setup site_id=%s", site_id)
            rds.hdel(REDIS_HASH_SITES_SETUP, f"{site_id}")
            rds.hdel(REDIS_HASH_IP_BLOCK, f"{site_id}")
            rds.delete(f"url_{site_id}")
        else:
            logger.info("Add site setup site_id=%s", site_id)
            rds.hset_str(REDIS_HASH_SITES_SETUP, site_id, s.package_code)
            rds.hset_str(REDIS_HASH_IP_BLOCK, site_id, s.ip_block)


def auto_check_limit(dao: HeatMapDAO, rds: RedisUtils, now: Optional[datetime] = None) -> None:
    now = now or datetime.now(jst)
    month_format = now.strftime("%Y%m")

    packages_limit = dao.get_list_package_limit()
    logger.info("(Check Limit) packages=%d month=%s", len(packages_limit), month_format)

    for p in packages_limit:
        pkg = p.package_code
        limit_req = int(p.limit_request)

        # Save quota for reference
        rds.hset_str(REDIS_HASH_PACKAGES_QUOTA, pkg, str(limit_req))

        pageview_key = f"pageview_{pkg}_{month_format}"
        pageview = rds.get_int(pageview_key)
        event_using = pageview if pageview else 0

        if event_using < limit_req:
            # Under limit: clear siteId in blacklist
            rds.hdel(REDIS_HASH_PACKAGES_LIMIT, f"{pkg}")

        else:
            # Exceeded limit: add to list limit
            rds.hset_str(REDIS_HASH_PACKAGES_LIMIT, pkg, "1")


def make_key_url(dao: HeatMapDAO, rds: RedisUtils) -> None:
    domain_ids = dao.get_list_heat_map_site_update()
    logger.info("(Make Key URL) domains_to_refresh=%d", len(domain_ids))

    for domain_id in domain_ids:
        count = refresh_redis_by_site(dao, rds, domain_id)
        logger.info("(Update URL) domain_id=%s urls_updated=%d", domain_id, count)


def refresh_redis_by_site(dao: HeatMapDAO, rds: RedisUtils, domain_id: str) -> int:
    redis_key = f"url_{domain_id}"
    rds.delete(redis_key)

    urls = dao.get_list_heat_map_url_configuration_by_domain_id(domain_id)
    urls_sorted = sorted(urls, key=lambda x: x.sort_item, reverse=True)

    for idx, cfg in enumerate(urls_sorted):
        # store each config as a member; score is index to keep order
        rds.zadd(redis_key, cfg.to_redis_member(), idx)

    return len(urls_sorted)


# -----------------------------
# Utility: step runner
# -----------------------------


def run_step(step_name: str, func: Callable[[], Any]) -> Any:
    try:
        logger.info("")
        logger.info("====== START STEP: %s ======", step_name)
        result = func()
        logger.info("====== DONE STEP: %s ======", step_name)
        logger.info("")
        return result
    except Exception as e:
        logger.error("====== ERROR STEP: %s ====== %s", step_name, str(e))
        logger.error("")
        raise


# -----------------------------
# Lambda entrypoint
# -----------------------------


def lambda_handler(event: Optional[dict] = None, context: Any = None) -> Dict[str, Any]:
    region = get_region()
    start_time = datetime.now(jst)
    cnx: Optional[pymysql.connections.Connection] = None
    try:
        logger.info("Lambda start: CHECK LIMIT HOURLY")

        secret = run_step("get_secret", lambda: get_secret(region))

        cnx = run_step("get_db_connection", lambda: get_db_connection(secret))

        dao = run_step("get_heat_map_dao", lambda: HeatMapDAO(cnx))

        # Redis client created inside steps to ensure proper lifecycle management and avoid stale connections
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        password = os.getenv("REDIS_PASSWORD", None)
        db = int(os.getenv("REDIS_DB", 0))
        rds = run_step("get redis wrapper", lambda: RedisUtils(host, port, password, db))

        run_step("auto_update_site_setup", lambda: auto_update_site_setup(dao, rds))
        run_step("auto_check_limit", lambda: auto_check_limit(dao, rds))
        run_step("make_key_url", lambda: make_key_url(dao, rds))

        execution_time = (datetime.now(jst) - start_time).total_seconds()
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Check Limit successfully executed", "execute_time": execution_time}),
        }

    finally:
        if cnx:
            cnx.close()


if __name__ == "__main__":
    lambda_handler()
