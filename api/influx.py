import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.bucket_api import BucketsApi
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUX_URL = os.getenv("INFLUXDB_HOST", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("DOCKER_INFLUXDB_INIT_ADMIN_TOKEN")
INFLUX_ORG = os.getenv("DOCKER_INFLUXDB_INIT_ORG")
INFLUX_BUCKET = os.getenv("DOCKER_INFLUXDB_INIT_BUCKET")
INFLUX_RETENTION = os.getenv("DOCKER_INFLUXDB_RETENTION", "30d")


def write_to_influx(measurement, tags, fields, timestamp=None):
    """
    Écrit un point dans InfluxDB
    :param measurement: nom de la mesure (ex: "glucose")
    :param tags: dict des tags (ex: {"user_id": "123"})
    :param fields: dict des champs (ex: {"value": 5.6})
    :param timestamp: datetime (optionnel), sinon maintenant
    """
    try:
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            write_api = client.write_api(write_options=SYNCHRONOUS)

            if not timestamp:
                timestamp = datetime.now()

            point = Point(measurement)

            for k, v in tags.items():
                point = point.tag(k, v)
            for k, v in fields.items():
                point = point.field(k, v)

            point = point.time(timestamp, WritePrecision.NS)

            write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG,
                            record=point, write_precision=WritePrecision.NS)
            # print(f"✅ Données envoyées dans InfluxDB : {measurement} {fields}")
    except Exception as e:
        print(f"❌ Erreur InfluxDB : {e}")


def read_from_influx(user_id, measurement="glucose", range_hours=24):
    """
    Lit les données InfluxDB pour un user_id donné.
    :param user_id: ID utilisateur à filtrer (tag)
    :param measurement: nom de la mesure (ex: "glucose")
    :param range_hours: fenêtre temporelle à lire (ex: 24h)
    :return: liste de points {time, fields...}
    """
    try:
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            query_api = client.query_api()

            flux_query = f'''
                from(bucket: "{INFLUX_BUCKET}")
                  |> range(start: -{range_hours}h)
                  |> filter(fn: (r) => r["_measurement"] == "{measurement}")
                  |> filter(fn: (r) => r["user_id"] == "{user_id}")
            '''

            tables = query_api.query(flux_query)

            results = []
            for table in tables:
                for record in table.records:
                    results.append({
                        "time": record.get_time().isoformat(),
                        "field": record.get_field(),
                        "value": record.get_value()
                    })

            return results

    except Exception as e:
        print(f"❌ Erreur lecture InfluxDB : {e}")
        return []


def parse_retention(ret_str: str) -> int:
    unit = ret_str[-1]
    value = int(ret_str[:-1])
    if unit == "d":
        return value * 24 * 3600
    elif unit == "h":
        return value * 3600
    elif unit == "m":
        return value * 60
    elif unit == "s":
        return value
    else:
        raise ValueError("Format de durée non supporté (utilise d/h/m/s)")


def init_influx_bucket():
    try:
        with InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG) as client:
            buckets_api: BucketsApi = client.buckets_api()

            retention_seconds = parse_retention(INFLUX_RETENTION)

            # Vérifie si le bucket existe déjà
            bucket = buckets_api.find_bucket_by_name(INFLUX_BUCKET)
            if bucket is None:
                # Création
                bucket = buckets_api.create_bucket(
                    bucket_name=INFLUX_BUCKET,
                    org=INFLUX_ORG,
                    retention_rules=[
                        {"type": "expire", "everySeconds": retention_seconds}]
                )
                print(
                    f"✅ Bucket '{INFLUX_BUCKET}' créé avec rétention {INFLUX_RETENTION}")
            else:
                # Mise à jour
                bucket.retention_rules = [
                    {"type": "expire", "everySeconds": retention_seconds}]
                buckets_api.update_bucket(bucket)
                print(
                    f"♻️ Bucket '{INFLUX_BUCKET}' mis à jour avec rétention {INFLUX_RETENTION}")

    except Exception as e:
        print(f"❌ Erreur init InfluxDB bucket : {e}")
