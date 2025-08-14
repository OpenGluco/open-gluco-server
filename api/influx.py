import os
from datetime import datetime

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUX_URL = os.getenv("INFLUXDB_HOST", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("DOCKER_INFLUXDB_INIT_ADMIN_TOKEN")
INFLUX_ORG = os.getenv("DOCKER_INFLUXDB_INIT_ORG")
INFLUX_BUCKET = os.getenv("DOCKER_INFLUXDB_INIT_BUCKET")


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
            print(f"✅ Données envoyées dans InfluxDB : {measurement} {fields}")
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
