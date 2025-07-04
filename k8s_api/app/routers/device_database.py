import pymysql
import logging

MYSQL_CONFIG = {
    "host": "10.64.243.119",
    "port": 3306,
    "user": "root",
    "password": "Byd@2024",
    "database": "hawkeye-test",
    "charset": "utf8mb4"
}

def get_conn():
    return pymysql.connect(**MYSQL_CONFIG)

def update_usage_info(device_name, userinfo, usage_info, environment_purpose, connect_info):
    """
    根据设备名查 test_bench.id，写 usage_log
    """
    try:
        conn = get_conn()
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

def update_versions(device_name, soc_version, mcu_version, integration_version):
    """
    根据设备名更新 soc_version、mcu_version、integration_version 字段
    """
    try:
        conn = get_conn()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE test_bench
                SET soc_version=%s, mcu_version=%s, integration_version=%s
                WHERE name=%s
            """, (soc_version, mcu_version, integration_version, device_name))
        conn.commit()
        logging.info(f"Version info updated: device={device_name}, soc={soc_version}, mcu={mcu_version}, integration={integration_version}")
    except Exception as e:
        logging.error(f"更新版本信息失败: {device_name}, 错误: {e}")
    finally:
        try: conn.close()
        except: pass

def insert_test_bench_task(device_name, task_name, task_type, user, start_time, result):
    """
    新建任务时插入一条记录（无end_time）
    """
    try:
        start_time_str = start_time.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        conn = get_conn()
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO test_bench_task (device_name, task_name, task_type, user, start_time, result)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (device_name, task_name, task_type, user, start_time_str, result))
        conn.commit()
        logging.info(f"Inserted test_bench_task: device={device_name}, job={task_name}, type={task_type}, user={user}, start={start_time_str}, result={result}")
    except Exception as e:
        logging.error(f"插入 test_bench_task 失败: {device_name}, 错误: {e}")
    finally:
        try: conn.close()
        except: pass

def finish_test_bench_task(device_name, task_name, start_time, end_time, result):
    """
    任务结束后根据 device_name、task_name、start_time（到秒）更新 end_time 和 result
    """
    try:
        start_time_str = start_time.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        end_time_str = end_time.replace(microsecond=0).strftime('%Y-%m-%d %H:%M:%S')
        conn = get_conn()
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE test_bench_task
                SET end_time=%s, result=%s
                WHERE device_name=%s AND task_name=%s AND start_time=%s
            """, (end_time_str, result, device_name, task_name, start_time_str))
        conn.commit()
        logging.info(f"Updated test_bench_task: device={device_name}, job={task_name}, start={start_time_str}, end={end_time_str}, result={result}")
    except Exception as e:
        logging.error(f"更新 test_bench_task 失败: {device_name}, 错误: {e}")
    finally:
        try: conn.close()
        except: pass