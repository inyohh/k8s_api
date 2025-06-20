import pymysql
import logging

MYSQL_CONFIG = {
    "host": "10.64.243.119",      # 修改为你的MySQL主机
    "port": 3306,
    "user": "root",       # 修改为你的用户名
    "password": "Byd@2024", # 修改为你的密码
    "database": "hawkeye-test",     # 修改为你的数据库名
    "charset": "utf8mb4"
}

def update_usage_info(device_name, userinfo, usage_info, environment_purpose, connect_info):
    """
    根据设备名查 test_bench.id，写 usage_log
    """
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM test_bench WHERE name=%s", (device_name,))
            row = cursor.fetchone()
            if not row:
                logging.warning(f"设备名未找到: {device_name}")
                return
            id = row[0]
            cursor.execute("""
                UPDATE test_bench
                SET user=%s, usage_info=%s, environment_purpose=%s, connect_info=%s
                WHERE id=%s
            """, (userinfo, usage_info, environment_purpose, connect_info, id))
        conn.commit()
        logging.info(f"Usage logged: device={device_name}, user={userinfo}, usage={usage_info}, purpose={environment_purpose}, connect={connect_info}")
    except Exception as e:
        logging.error(f"写入 test_bench 失败: {id} {device_name}, 错误: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass

def get_bench_status(device_name):
    """
    通过设备名获取 bench_status
    """
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("SELECT bench_status FROM test_bench WHERE name=%s", (device_name,))
            row = cursor.fetchone()
            if row:
                return row[0]
            else:
                logging.warning(f"设备名未找到: {device_name}")
                return None
    except Exception as e:
        logging.error(f"获取 bench_status 失败: {device_name}, 错误: {e}")
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass

def update_bench_status(device_name, new_status):
    """
    根据设备名更新 bench_status
    """
    try:
        conn = pymysql.connect(**MYSQL_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute("UPDATE test_bench SET bench_status=%s WHERE name=%s", (new_status, device_name))
        conn.commit()
        logging.info(f"Bench status updated: device={device_name}, new_status={new_status}")
    except Exception as e:
        logging.error(f"更新 bench_status 失败: {device_name}, 错误: {e}")
    finally:
        try:
            conn.close()
        except Exception:
            pass
