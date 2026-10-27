-- Tables brutes : un relevé par station et par interrogation du flux GBFS.
CREATE DATABASE IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.station_status
(
    station_id          UInt64,
    station_code        LowCardinality(String),
    polled_at           DateTime('UTC'),
    last_reported       DateTime('UTC'),
    num_bikes_available UInt16,
    num_mechanical      UInt16,
    num_ebike           UInt16,
    num_docks_available UInt16,
    is_installed        UInt8,
    is_renting          UInt8,
    is_returning        UInt8,
    ingested_at         DateTime('UTC') DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMMDD(polled_at)
ORDER BY (station_id, polled_at)
TTL polled_at + INTERVAL 90 DAY;

CREATE TABLE IF NOT EXISTS raw.station_information
(
    station_id   UInt64,
    station_code LowCardinality(String),
    name         String,
    lat          Float64,
    lon          Float64,
    capacity     UInt16,
    updated_at   DateTime('UTC')
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY station_id;
