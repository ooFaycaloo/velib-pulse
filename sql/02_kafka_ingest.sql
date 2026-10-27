-- Ingestion temps réel : ClickHouse consomme directement les topics Kafka/Redpanda
-- (moteur Kafka) et une vue matérialisée écrit chaque message dans la table brute.
-- Utilisé par docker-compose. En développement sans Kafka, le producteur écrit directement en base.

CREATE TABLE IF NOT EXISTS raw.station_status_queue
(
    station_id          UInt64,
    station_code        String,
    polled_at           DateTime('UTC'),
    last_reported       DateTime('UTC'),
    num_bikes_available UInt16,
    num_mechanical      UInt16,
    num_ebike           UInt16,
    num_docks_available UInt16,
    is_installed        UInt8,
    is_renting          UInt8,
    is_returning        UInt8
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'velib.station_status',
         kafka_group_name = 'clickhouse-velib-status',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1,
         kafka_skip_broken_messages = 100;

CREATE MATERIALIZED VIEW IF NOT EXISTS raw.station_status_mv TO raw.station_status AS
SELECT * FROM raw.station_status_queue;

CREATE TABLE IF NOT EXISTS raw.station_information_queue
(
    station_id   UInt64,
    station_code String,
    name         String,
    lat          Float64,
    lon          Float64,
    capacity     UInt16,
    updated_at   DateTime('UTC')
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'redpanda:9092',
         kafka_topic_list = 'velib.station_information',
         kafka_group_name = 'clickhouse-velib-info',
         kafka_format = 'JSONEachRow';

CREATE MATERIALIZED VIEW IF NOT EXISTS raw.station_information_mv TO raw.station_information AS
SELECT * FROM raw.station_information_queue;
